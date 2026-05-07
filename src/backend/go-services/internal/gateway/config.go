package gateway

import runtimeconfig "rag-system/config"

type ServiceConfig = runtimeconfig.ServiceConfig
type GatewayConfig = runtimeconfig.GatewayConfig

func LoadConfig(args []string) (*GatewayConfig, runtimeconfig.TelemetryConfig, error) {
	cfg, telemetryCfg, err := runtimeconfig.LoadGatewayConfig(args)
	if err != nil {
		return nil, runtimeconfig.TelemetryConfig{}, err
	}
	return &cfg, telemetryCfg, nil
}
