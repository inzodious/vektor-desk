FROM caddy:2.10.2-builder AS build
RUN xcaddy build --with github.com/caddy-dns/porkbun@v0.3.1

FROM caddy:2.10.2
COPY --from=build /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
RUN PORKBUN_API_KEY=check PORKBUN_API_SECRET_KEY=check caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
ARG DESK_BUILD=dev
LABEL org.opencontainers.image.revision=$DESK_BUILD
