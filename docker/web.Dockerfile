# AgentForge Arena — web service (built Vite SPA, served static by nginx).
#
# Stage 1 builds web/ with Node. Stage 2 serves the static dist/ and
# reverse-proxies /api to the `api` service, so the browser talks to ONE
# origin (http://localhost:8080) with no CORS gymnastics.

# ---- build stage ----------------------------------------------------------
FROM node:23-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- serve stage ----------------------------------------------------------
FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
