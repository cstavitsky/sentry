from __future__ import annotations

from typing import Any, MutableMapping

from arroyo import Topic
from arroyo.backends.kafka.configuration import build_kafka_consumer_configuration
from arroyo.backends.kafka.consumer import KafkaConsumer, KafkaPayload
from arroyo.commit import ONCE_PER_SECOND
from arroyo.processing.processor import StreamProcessor

from sentry.profiles.consumers.process.factory import ProcessProfileStrategyFactory
from sentry.utils import kafka_config
from sentry.utils.batching_kafka_consumer import create_topics


def get_profiles_process_consumer(
    topic: str,
    group_id: str,
    auto_offset_reset: str,
    strict_offset_reset: bool,
    force_topic: str | None,
    force_cluster: str | None,
) -> StreamProcessor[KafkaPayload]:
    topic = force_topic or topic
    consumer_config = get_config(
        topic,
        group_id,
        auto_offset_reset=auto_offset_reset,
        strict_offset_reset=strict_offset_reset,
        force_cluster=force_cluster,
    )
    consumer = KafkaConsumer(consumer_config)
    return StreamProcessor(
        consumer=consumer,
        topic=Topic(topic),
        processor_factory=ProcessProfileStrategyFactory(),
        commit_policy=ONCE_PER_SECOND,
    )


def get_config(
    topic: str,
    group_id: str,
    auto_offset_reset: str,
    strict_offset_reset: bool,
    force_cluster: str | None,
) -> MutableMapping[str, Any]:
    cluster_name: str = force_cluster or kafka_config.get_topic_definition(topic)["cluster"]
    create_topics(cluster_name, [topic])
    return build_kafka_consumer_configuration(
        kafka_config.get_kafka_consumer_cluster_options(
            cluster_name,
        ),
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        strict_offset_reset=strict_offset_reset,
    )
