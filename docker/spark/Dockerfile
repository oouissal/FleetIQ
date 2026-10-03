# FleetIQ Spark Structured Streaming image
# Official apache/spark image (bitnami/spark was removed from Docker Hub in
# 2026, hence the switch — documented). Spark 4.2 matches local PySpark.
FROM apache/spark:4.2.0-scala2.13-java17-python3-ubuntu

USER root

# Python deps used by the streaming job (aligned with the image's Spark)
RUN pip install --no-cache-dir \
    "pyspark==4.2.0" \
    kafka-python \
    pandas \
    pyarrow \
    "pydantic>=2" \
    pydantic-settings

# s3a support for MinIO (matching Hadoop 3.4.x shipped with Spark 4.2).
# Hadoop 3.4.1 requires the AWS SDK v2 bundle classes (for example
# software.amazon.awssdk.auth.credentials.AwsCredentialsProvider) in addition
# to the v1 AWS SDK bundle.
RUN curl -fsSL -o /opt/spark/jars/hadoop-aws-3.4.1.jar \
        https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar \
 && curl -fsSL -o /opt/spark/jars/aws-java-sdk-bundle-1.12.767.jar \
        https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.767/aws-java-sdk-bundle-1.12.767.jar \
 && curl -fsSL -o /opt/spark/jars/aws-sdk-java-bundle-2.31.18.jar \
        https://repo1.maven.org/maven2/software/amazon/awssdk/bundle/2.31.18/bundle-2.31.18.jar

# Kafka structured streaming connector (not bundled in the apache/spark image)
# Spark 4.2 ships with the 0-10 connector artifact naming scheme. The main
# connector jar is paired with a token-provider jar that contains the runtime
# KafkaConfigUpdater class required by the structured streaming source.
RUN curl -fsSL -o /opt/spark/jars/spark-sql-kafka-0-10_2.13-4.2.0.jar \
        https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.13/4.2.0/spark-sql-kafka-0-10_2.13-4.2.0.jar \
 && curl -fsSL -o /opt/spark/jars/spark-token-provider-kafka-0-10_2.13-4.2.0.jar \
        https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.13/4.2.0/spark-token-provider-kafka-0-10_2.13-4.2.0.jar \
 && curl -fsSL -o /opt/spark/jars/kafka-clients-3.9.1.jar \
        https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.9.1/kafka-clients-3.9.1.jar

# Project code (streaming package only; spark-submit adds the root to sys.path)
COPY streaming /opt/fleetiq/streaming
WORKDIR /opt/fleetiq

ENV PYSPARK_PYTHON=python3
ENV SPARK_UI_PORT=4040

CMD ["spark-submit", "--master", "local[*]", \
     "--conf", "spark.ui.port=4040", \
     "--conf", "spark.driver.bindAddress=0.0.0.0", \
     "--conf", "spark.sql.streaming.forceDeleteTempCheckpointLocation=true", \
     "/opt/fleetiq/streaming/spark/streaming_job.py", "--mode", "kafka"]

