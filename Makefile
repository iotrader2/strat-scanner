.PHONY: dev setup refresh refresh-universe test typecheck

dev:
	npm run dev

setup:
	npm run setup

refresh:
	npm run refresh

refresh-universe:
	npm run refresh:universe

test:
	npm test

typecheck:
	npm run typecheck
