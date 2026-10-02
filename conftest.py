# Root conftest: ensures the project root is importable from tests/.
import os

# Tests use plain-path (filesystem) MLflow tracking stores in tmp dirs;
# MLflow 3.x requires this explicit opt-in for the file store.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
