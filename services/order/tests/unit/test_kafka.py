import asyncio
import threading

import pytest
from market_order.adapters.kafka import KafkaPublisher


@pytest.mark.anyio
async def test_kafka_produce_and_poll_run_outside_event_loop():
    loop_thread = threading.get_ident()
    threads = []
    observed = {}

    class Producer:
        def produce(self, topic, *, key, value, on_delivery):
            threads.append(threading.get_ident())
            observed.update(topic=topic, key=key, value=value, callback=on_delivery)

        def poll(self, timeout):
            threads.append(threading.get_ident())
            observed["callback"](None, object())
            return 0

        def flush(self, timeout):
            threads.append(threading.get_ident())
            return 0

    def factory(config):
        threads.append(threading.get_ident())
        assert config["enable.idempotence"] is True
        assert config["acks"] == "all"
        return Producer()

    publisher = KafkaPublisher("kafka:9092", 1, producer_factory=factory)
    await publisher.send("order", {"event_id": "event"})
    await publisher.close()
    assert observed["topic"] == "orders.events" and observed["key"] == b"order"
    assert b"event" in observed["value"]
    assert threads and all(thread != loop_thread for thread in threads)


@pytest.mark.anyio
async def test_kafka_delivery_failure_is_not_an_ack():
    class Producer:
        def produce(self, topic, *, key, value, on_delivery):
            self.callback = on_delivery

        def poll(self, timeout):
            self.callback(RuntimeError("broker absent"), object())
            return 0

        def flush(self, timeout):
            return 0

    publisher = KafkaPublisher("kafka:9092", 1, producer_factory=lambda config: Producer())
    with pytest.raises(RuntimeError, match="broker absent"):
        await publisher.send("order", {})
    await asyncio.sleep(0)
