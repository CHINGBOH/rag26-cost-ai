package gateway

import (
	"regexp"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	requestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "gateway_requests_total",
			Help: "Total number of HTTP requests",
		},
		[]string{"method", "path", "status"},
	)

	requestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "gateway_request_duration_seconds",
			Help:    "HTTP request duration in seconds",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "path"},
	)
)

// dynamicPathPatterns maps known dynamic route segments to normalized labels.
var dynamicPathPatterns = []struct {
	re      *regexp.Regexp
	replace string
}{
	{regexp.MustCompile(`^/api/documents/[^/]+$`), "/api/documents/{id}"},
	{regexp.MustCompile(`^/api/ocr/pdf/async/[^/]+$`), "/api/ocr/pdf/async/{job_id}"},
	{regexp.MustCompile(`^/api/pipeline/files/[^/]+$`), "/api/pipeline/files/{file_id}"},
}

// normalizePath converts a concrete request path into a stable metric label.
func normalizePath(path string) string {
	for _, p := range dynamicPathPatterns {
		if p.re.MatchString(path) {
			return p.replace
		}
	}
	return path
}

// RecordMetrics observes request count and duration for Prometheus.
func RecordMetrics(method, path, status string, duration float64) {
	normalized := normalizePath(path)
	requestsTotal.WithLabelValues(method, normalized, status).Inc()
	requestDuration.WithLabelValues(method, normalized).Observe(duration)
}

// MetricsHandler returns the gin handler for Prometheus metrics.
func MetricsHandler() gin.HandlerFunc {
	return gin.WrapH(promhttp.Handler())
}
