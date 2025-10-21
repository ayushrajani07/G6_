from prometheus_client import REGISTRY

from src.metrics import register_build_info, setup_metrics_server  # facade import

metrics,_ = setup_metrics_server(use_custom_registry=False, reset=True)
register_build_info(metrics, version='1.0', git_commit='a', config_hash='h1')
register_build_info(metrics, version='1.1', git_commit='b', config_hash='h2')
lines=[]
for collector in list(getattr(REGISTRY,'_names_to_collectors', {}).values()):
    try:
        for metric in collector.collect():
            for sample in metric.samples:
                if sample.name=='g6_build_info':
                    label_str=','.join(f"{k}='{v}'" for k,v in sorted(sample.labels.items()))
                    lines.append(f"{sample.name}{{{label_str}}} {sample.value}")
    except Exception:
        pass
print('\n'.join(lines) or 'NO_BUILD_INFO')
