
# 游戏存档同步/应用Makefile
.PHONY: sync apply

# 同步存档到Git工程
sync:
	@python scripts/save.py sync

# 应用Git工程中的存档到游戏目录
apply:
	@python scripts/save.py apply

help:
	@echo "sync                 -- 同步."
	@echo "cleanpath            -- 清空所有路径."
	@echo "blog                 -- 生成博客"
	@echo "blog_server          -- 生成博客并启动本地服务"
	@echo "blog_deploy          -- 生成博客并发布到远程仓库"
	@echo "blog_template        -- 生成博客文档模板"
	@echo "simple               -- 快速完成清空路径, 提交 git, 和发布博客"
