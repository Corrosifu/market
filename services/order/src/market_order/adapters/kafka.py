"""Le client Kafka synchrone ne s'exécute jamais sur la boucle ASGI."""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Protocol, cast

from confluent_kafka import Producer


class ProducerLike(Protocol):
    def produce(
        self, topic: str, *, key: bytes, value: bytes, on_delivery: Callable[[object | None, object], None]
    ) -> None: ...
    def poll(self, timeout: float) -> int: ...
    def flush(self, timeout: float) -> int: ...


def create_producer(config: dict[str, object]) -> ProducerLike:
    return cast(ProducerLike, Producer(config))


class KafkaPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        timeout: float,
        *,
        producer_factory: Callable[[dict[str, object]], ProducerLike] = create_producer,
    ) -> None:
        self.config: dict[str, object] = {
            "bootstrap.servers": bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": max(1, int(timeout * 1000)),
            "socket.timeout.ms": 1000,
        }
        self.timeout = timeout
        self.factory = producer_factory
        self.producer: ProducerLike | None = None

    def _send(self, order_id: str, envelope: dict[str, object]) -> None:
        if self.producer is None:
            self.producer = self.factory(self.config)
        delivered = False
        failure: object | None = None

        def on_delivery(error: object | None, message: object) -> None:
            nonlocal delivered, failure
            failure, delivered = error, True

        self.producer.produce(
            "orders.events", key=order_id.encode(), value=json.dumps(envelope).encode(), on_delivery=on_delivery
        )
        deadline = time.monotonic() + self.timeout
        while not delivered:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Kafka n'a pas accusé réception à temps")
            self.producer.poll(min(0.1, remaining))
        if failure is not None:
            raise RuntimeError(str(failure))

    async def send(self, order_id: str, event: dict[str, object]) -> None:
        await asyncio.to_thread(self._send, order_id, event)

    async def close(self) -> None:
        if self.producer is not None:
            await asyncio.to_thread(self.producer.flush, self.timeout)
