# Web image: Vite build -> nginx. Build from the repo root:
#   docker build -f infra/web.Dockerfile --build-arg VITE_API_URL=http://localhost:8080 -t pla-web .
# nginx proxies /api to the api service, so VITE_API_URL is normally the web origin itself.

FROM node:20-alpine AS build
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
# The app imports fixtures/types from ../../contract (Vite alias @contract).
COPY contract /src/contract
ARG VITE_API_URL=http://localhost:8080
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build:live

FROM nginx:1.27-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
