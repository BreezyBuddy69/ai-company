FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Baked in at build time — Next.js inlines NEXT_PUBLIC_* into the client bundle.
ARG NEXT_PUBLIC_API_URL=
ARG NEXT_PUBLIC_API_KEY=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_KEY=$NEXT_PUBLIC_API_KEY
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Next's standalone server does `process.env.HOSTNAME || '0.0.0.0'`, and Docker
# sets HOSTNAME to the container id in every container. Without this line the
# server binds to the container id alone — so `localhost:3000` is refused from
# inside, the healthcheck below fails, Traefik drops the unhealthy container
# from its pool, and the site serves 404 while the container looks "running".
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
# Checks that something is listening, not that a page renders. The previous
# `wget /` version also failed whenever DASHBOARD_USER/PASSWORD were set, since
# middleware.ts answers 401 and busybox wget treats that as an error — an auth
# setting would have silently taken the site off Traefik.
#
# Uses node rather than nc or wget: node is the image's whole reason to exist,
# so it cannot be missing, and a healthcheck that fails because its own tool is
# absent looks exactly like the outage it is supposed to detect.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "require('net').connect(3000,'127.0.0.1').on('connect',function(){process.exit(0)}).on('error',function(){process.exit(1)})"

CMD ["node", "server.js"]
