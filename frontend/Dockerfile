# ── Stage 1: Install dependencies ────────────────────
FROM node:20-slim AS deps
WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ── Stage 2: Build ───────────────────────────────────
FROM node:20-slim AS builder
WORKDIR /build

# Copy cached node_modules from deps stage
COPY --from=deps /build/node_modules node_modules
COPY . .
RUN npm run build

# ── Stage 3: Serve ───────────────────────────────────
FROM nginx:alpine-slim

# Remove default nginx config
RUN rm -rf /usr/share/nginx/html/*

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80
