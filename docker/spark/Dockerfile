# FleetIQ Spark Structured Streaming image
# Based on bitnami/spark (Java 11 inside the container, no local Java needed).
FROM bitnami/spark:3.5

USER root

# Python deps used by the streaming job (pinned to the image's Spark minor)
RUN pip install --no-cache-dir \
    "pyspark==3.5.*" \
    kafka-python \
    pandas \
    pyarrow \
    "pydantic>=2" \
    pydantic-settings

# s3a support for MinIO (Hadoop AWS module + AWS SDK)
RUN curl -fsSL -o /opt/bitnami/spark/jars/hadoop-aws-3.3.4.jar \
        https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar \
 && curl -fsSL -o /opt/bitnami/spark/jars/aws-java-sdk-bundle-1.12.367.jar \
        https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.367/aws-java-sdk-bundle-1.12.367.jar

# Project code (streaming package only; spark-submit adds the root to sys.path)
COPY streaming /opt/fleetiq/streaming
WORKDIR /opt/fleetiq

# Driver UI must be reachable for the container healthcheck
ENV SPARK_UI_PORT=4040

CMD ["spark-submit", "--master", "local[*]", \
     "--conf", "spark.ui.port=4040", \
     "--conf", "spark.driver.bindAddress=0.0.0.0", \
     "--conf", "spark.sql.streaming.forceDeleteTempCheckpointLocation=true", \
     "/opt/fleetiq/streaming/spark/streaming_job.py", "--mode", "kafka"]
