FROM node:22-alpine AS builder
WORKDIR /app/server
COPY server/package.json server/package-lock.json* ./
RUN npm ci
COPY server ./
COPY types /app/types
RUN npm run build

FROM node:22-alpine
WORKDIR /app/server
ENV NODE_ENV=production
COPY server/package.json server/package-lock.json* ./
RUN npm ci --omit=dev
COPY --from=builder /app/server/dist ./dist
EXPOSE 8020
CMD ["npm", "start"]
