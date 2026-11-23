# market_common

Mécanismes techniques partagés par les services de Market : réglages (`settings`), journaux JSON avec `trace_id`
(`logging`), routes de santé (`health`) et résilience des appels sortants (`resilience`). Aucune règle métier.

## Résilience des appels sortants (`market_common.resilience`)

Bibliothèque standard seule (`asyncio`, `time`). Chaque mécanisme reçoit une **fabrique** d'appel
(`Callable[[], Awaitable[T]]`, par exemple `lambda: client.post(...)`), jamais une coroutine déjà créée : le retry
doit pouvoir relancer l'appel.

| Mécanisme | API | Comportement |
|---|---|---|
| Délai | `with_timeout(operation, seconds)` | annule l'appel au délai et lève `CallTimeoutError` (sous-classe de `TimeoutError`) |
| Retry | `RetryPolicy(retry_on, attempts=3, backoff_seconds=0.1, sleep=asyncio.sleep).call(operation, *, idempotent)` | rejoue seulement un appel déclaré `idempotent=True`, seulement sur les exceptions de `retry_on`, au plus `attempts` tentatives, puis relève l'exception d'origine ; attente fixe entre deux tentatives, au plus 0,2 s (`MAX_BACKOFF_SECONDS`, contrôlé à la construction) ; `CircuitOpenError` et `BulkheadFullError` ne sont jamais rejouées, même désignées |
| Circuit breaker | `CircuitBreaker(name, *, failure_threshold, reset_timeout_seconds, failure_types, clock=time.monotonic).call(operation)` | compte chaque appel qui lève une exception de `failure_types` ; un succès remet le compteur à zéro ; ouvert au seuil, il refuse sans appeler (`CircuitOpenError`) ; après `reset_timeout_seconds`, un seul appel d'essai passe : réussi, il referme, échoué, il rouvre. État lisible : `breaker.state` vaut `closed`, `open` ou `half_open` (`CircuitState`, une `StrEnum`) |
| Bulkhead | `Bulkhead(name, *, max_concurrent, max_queue=0).call(operation)` | au plus `max_concurrent` appels simultanés et `max_queue` en attente ; au-delà, refus immédiat (`BulkheadFullError`) |

Une exception **hors** de `failure_types` (un résultat métier : paiement refusé 402, stock insuffisant 409) n'est
ni comptée comme panne, ni rejouée si elle est hors de `retry_on` : elle prouve que la dépendance répond et vaut un
succès pour le circuit. Le délai, les tentatives, l'attente (`sleep`) et l'horloge (`clock`) sont injectables : les
tests n'attendent pas réellement.

### Composition

Ordre retenu : **retry autour du circuit autour du délai par tentative, le tout dans le bulkhead**. Le bulkhead est
pris une seule fois pour toutes les tentatives ; chaque tentative a son propre délai et passe par le circuit, qui la
compte si elle échoue ; dès que le circuit s'ouvre, `CircuitOpenError` interrompt le retry. `call_resilient` écrit
cette composition :

```python
import httpx
from market_common.resilience import (
    Bulkhead, CallTimeoutError, CircuitBreaker, RetryPolicy, call_resilient,
)


class UpstreamUnavailable(Exception):
    """Réponse 5xx de la dépendance : compte comme panne."""


FAILURES = (CallTimeoutError, httpx.TransportError, UpstreamUnavailable)  # délai, connexion (DNS compris), 5xx

payment_breaker = CircuitBreaker("payment", failure_threshold=3, reset_timeout_seconds=10.0, failure_types=FAILURES)
payment_bulkhead = Bulkhead("payment", max_concurrent=10)
retry = RetryPolicy(retry_on=FAILURES, attempts=3, backoff_seconds=0.1)


async def pay(client: httpx.AsyncClient, order_id: str, body: dict[str, object]) -> httpx.Response:
    async def post() -> httpx.Response:
        response = await client.post("/v1/payments", json=body, headers={"Idempotency-Key": order_id})
        if response.status_code >= 500:
            raise UpstreamUnavailable(response.status_code)
        return response  # 2xx et 4xx (402, 409) : résultat métier, ni rejoué, ni compté

    return await call_resilient(
        post, idempotent=True, timeout_seconds=1.0,
        retry=retry, breaker=payment_breaker, bulkhead=payment_bulkhead,
    )
```

La même composition, écrite à la main (extrait autonome) :

```python
import httpx
from market_common.resilience import (
    Bulkhead, CallTimeoutError, CircuitBreaker, RetryPolicy, with_timeout,
)


class UpstreamUnavailable(Exception):
    """Réponse 5xx de la dépendance : compte comme panne."""


FAILURES = (CallTimeoutError, httpx.TransportError, UpstreamUnavailable)

payment_breaker = CircuitBreaker("payment", failure_threshold=3, reset_timeout_seconds=10.0, failure_types=FAILURES)
payment_bulkhead = Bulkhead("payment", max_concurrent=10)
retry = RetryPolicy(retry_on=FAILURES, attempts=3, backoff_seconds=0.1)


async def pay(client: httpx.AsyncClient, order_id: str, body: dict[str, object]) -> httpx.Response:
    async def post() -> httpx.Response:
        response = await client.post("/v1/payments", json=body, headers={"Idempotency-Key": order_id})
        if response.status_code >= 500:
            raise UpstreamUnavailable(response.status_code)
        return response

    async def attempt() -> httpx.Response:  # une tentative : délai propre, comptée par le circuit
        return await payment_breaker.call(lambda: with_timeout(post, 1.0))

    return await payment_bulkhead.call(lambda: retry.call(attempt, idempotent=True))
```

Points à respecter :

- `CallTimeoutError` doit figurer dans `failure_types` et `retry_on`, sinon un délai dépassé n'est ni compté ni
  rejoué.
- Pour qu'une commande suivante soit refusée sans appel, le seuil du circuit doit être inférieur ou égal au nombre
  de tentatives d'une commande.
- Pire durée d'un appel : `attempts × timeout_seconds + (attempts − 1) × backoff_seconds`, plus l'attente éventuelle
  dans la file du bulkhead.
- Bulkhead : laisser `max_queue` à 0. Le délai s'applique à l'intérieur du bulkhead, à chaque tentative : l'attente
  d'une place dans la file n'est bornée par aucun délai et ferait dépasser le budget de la requête. Avec
  `max_queue=0`, un appel au-delà de `max_concurrent` est refusé tout de suite (`BulkheadFullError`).
- Un circuit et un bulkhead par dépendance, créés une fois (au démarrage du service) et partagés par les requêtes.
  Le bulkhead utilise un `asyncio.Semaphore` : il doit servir dans une seule boucle d'événements.
