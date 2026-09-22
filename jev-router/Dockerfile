FROM node:22-alpine AS builder
WORKDIR /app/jev-router
COPY jev-router/package.json jev-router/package-lock.json* ./
RUN npm ci
COPY jev-router/tsconfig.json ./
COPY jev-router/src ./src
RUN npm run build

FROM node:22-alpine
WORKDIR /app/jev-router
ENV NODE_ENV=production
COPY jev-router/package.json jev-router/package-lock.json* ./
RUN npm ci --omit=dev
COPY --from=builder /app/jev-router/dist ./dist
EXPOSE 8030
CMD ["npm", "start"]
