# syntax=docker/dockerfile:1
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
COPY vite.config.js ./
COPY index.html ./
COPY src ./src
RUN npm ci --prefer-offline --no-audit --no-fund || npm install && npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
