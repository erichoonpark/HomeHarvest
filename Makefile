.PHONY: dashboard-publish dashboard-deploy-secure

dashboard-publish:
	./scripts/build_dashboard_publish.sh

dashboard-deploy-secure:
	./scripts/deploy_cloudflare_pages.sh
