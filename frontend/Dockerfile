FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_SENTRY_DSN
ARG VITE_SENTRY_ENVIRONMENT=production
ARG VITE_OTA_CHANNEL=production
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ENV VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT
ENV VITE_OTA_CHANNEL=$VITE_OTA_CHANNEL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.d/20-mobile-association-files.sh /docker-entrypoint.d/20-mobile-association-files.sh
EXPOSE 80
