.PHONY: test dashboard-publish dashboard-deploy-github

test:
	bash ./scripts/test.sh

dashboard-publish:
	./scripts/build_dashboard_publish.sh

dashboard-deploy-github:
	@echo "Firebase Hosting deploy runs from .github/workflows/deploy_dashboard_firebase.yml"
	@echo "Push to master or trigger the workflow manually in GitHub Actions."
