# alpine/git bringt keinen MQTT-Client mit; mosquitto-clients (~1 MB) ergänzt mosquitto_pub,
# damit sync.sh nach jedem Durchlauf seinen Zustand melden kann. Multi-arch, läuft auf arm64.
FROM alpine/git:2.47.2
RUN apk add --no-cache mosquitto-clients
