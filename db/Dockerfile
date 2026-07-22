FROM pgvector/pgvector:pg16
# Docker Manager deploys only pull this compose file, never the repo itself
# — a bind-mounted ./db/init.sql (what docker-compose.yml uses) has nothing
# to mount. Bake the schema+seed into the image instead.
COPY init.sql /docker-entrypoint-initdb.d/01_init.sql
