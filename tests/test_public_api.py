import zamp_sdk


class TestPublicApi:
    def test_action_executor_importable(self):
        from zamp_sdk import ActionExecutor

        assert hasattr(ActionExecutor, "execute")

    def test_retry_policy_importable(self):
        from zamp_sdk import RetryPolicy

        assert hasattr(RetryPolicy, "default")

    def test_sdk_config_importable(self):
        from zamp_sdk import SdkConfig

        assert hasattr(SdkConfig, "model_fields")

    def test_execution_mode_importable(self):
        from zamp_sdk import ExecutionMode

        assert ExecutionMode.SYNC.value == "SYNC"
        assert ExecutionMode.ASYNC.value == "ASYNC"
        assert ExecutionMode.INLINE.value == "INLINE"

    def test_all_exports(self):
        assert "ActionExecutor" in zamp_sdk.__all__
        assert "RetryPolicy" in zamp_sdk.__all__
        assert "SdkConfig" in zamp_sdk.__all__
        assert "ExecutionMode" in zamp_sdk.__all__
        assert "BaseActivity" in zamp_sdk.__all__
        assert "BaseWorkflow" in zamp_sdk.__all__
        assert "CodeWorkflowCoreParams" in zamp_sdk.__all__
        assert "UniversalWorkflowV2Input" in zamp_sdk.__all__
        assert "ExecuteDynamicActivityWorkflowInput" in zamp_sdk.__all__
        assert "ExecuteDynamicActivityWorkflowOutput" in zamp_sdk.__all__
        assert len(zamp_sdk.__all__) == 10
