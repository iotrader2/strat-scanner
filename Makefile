.PHONY: dev setup refresh refresh-universe themes-report themes-sync backtest-leaders score-report test typecheck

dev:
	npm run dev

setup:
	npm run setup

refresh:
	npm run refresh

refresh-universe:
	npm run refresh:universe

themes-report:
	npm run themes:report

themes-sync:
	npm run themes:sync

backtest-leaders:
	npm run backtest:leaders

score-report:
	npm run score:report

test:
	npm test

typecheck:
	npm run typecheck
