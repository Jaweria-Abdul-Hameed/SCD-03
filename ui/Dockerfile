# RAHBAR chat UI — nginx, non-root.
# nginx runs as UID 10001 (see k8s securityContext); the stock nginx image
# runs as root by default, so we only add the config + static page and
# switch user. Writable paths (/tmp, /var/cache/nginx, /var/run) are
# provided as emptyDir volumes by the UI Deployment (readOnlyRootFilesystem).
FROM nginx:1.27-alpine
RUN apk update && apk upgrade --no-cache
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
RUN mkdir -p /var/cache/nginx /var/run /tmp \
    && chown -R 10001:10001 /var/cache/nginx /var/run /tmp /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html
USER 10001
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
