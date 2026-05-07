package gateway

import "testing"

func TestFindTargetServiceRoutesExecutorEndpointsToRetrieval(t *testing.T) {
	service, found := findTargetService("/api/v1/executor/event-status/6")
	if !found {
		t.Fatalf("expected executor route to be mapped")
	}
	if service != "retrieval" {
		t.Fatalf("expected retrieval service, got %q", service)
	}
}
