# Entregable 1 DevOps: Despliegue Blue/Green

Notes API desplegada en Kubernetes (Docker Desktop) usando una estrategia
Blue/Green: v1 (blue) y v2 (green) corren en paralelo, y el tráfico se
cambia entre ellas parcheando el selector del Service, sin downtime.

## Prerrequisitos

- Docker Desktop con Kubernetes habilitado (Settings > Kubernetes > Enable Kubernetes)
- `kubectl` (incluido con Docker Desktop)

Verificar que el cluster esté activo y apuntando a Docker Desktop:

```bash
kubectl config use-context docker-desktop
kubectl get nodes
```

## Diferencia entre v1 y v2

v2 agrega un endpoint nuevo, `GET /stats`, que devuelve la cantidad total
de notas guardadas. Este endpoint solo se registra cuando `APP_VERSION`
empieza con `v2` (ver `main.py`), así que blue (v1) no lo tiene y green
(v2) sí. `/` y `/health` siguen reportando `version` y `color` en ambas.

Para verificarlo una vez desplegado (pasos 2 a 4 más abajo):

```bash
curl -s -o /dev/null -w 'blue /stats -> %{http_code}\n' http://localhost/stats
# blue /stats -> 404

./switch-to-green.sh
curl http://localhost/stats
# {"total_notes":0,"version":"v2.0.0"}
```

## 1. Construir las imágenes

El Kubernetes de Docker Desktop comparte el mismo daemon de Docker, así que
las imágenes construidas localmente ya son visibles para el cluster (no
hace falta cargarlas aparte).

```bash
docker build -t devops-app:v1 .
docker build -t devops-app:v2 .
```

## 2. Desplegar Blue y Green

```bash
kubectl apply -f k8s/blue-deployment.yaml
kubectl apply -f k8s/green-deployment.yaml
kubectl apply -f k8s/service.yaml
```

El Service arranca apuntando a `version: blue`.

```bash
kubectl get pods -l app=devops-app -L version
```

## 3. Acceder al servicio

`k8s/service.yaml` es un Service de tipo `LoadBalancer`. El Kubernetes de
Docker Desktop expone los Services `LoadBalancer` directamente en
`localhost`, en el `port` del Service (no hace falta `minikube service` ni
un NodePort):

```bash
curl http://localhost/health
# {"status":"ok","health_param":"default","version":"v1.0.0","color":"blue"}
```

## 4. Cutover a Green

```bash
./switch-to-green.sh
curl http://localhost/health
# {"status":"ok","health_param":"default","version":"v2.0.0","color":"green"}
```

Para volver atrás: `./switch-to-blue.sh`.

## 5. Verificar el cambio sin downtime

```bash
while true; do curl -s http://localhost/health; echo; sleep 1; done
```

Mientras el loop corre, ejecutar `./switch-to-green.sh` en otra terminal;
la salida pasa de blue a green sin ningún request fallido.

## Troubleshooting: imagen desactualizada

Si reconstruís `devops-app:v1` o `devops-app:v2` después de ya haberlos
desplegado, Kubernetes puede seguir usando la imagen vieja cacheada bajo
ese mismo tag (`imagePullPolicy: IfNotPresent` no detecta que el contenido
cambió). Si ves código viejo corriendo en el pod, forzá la limpieza del
cache de imágenes del nodo:

```bash
kubectl debug node/desktop-control-plane -it --image=alpine --profile=sysadmin -- \
  chroot /host crictl rmi docker.io/library/devops-app:v1 docker.io/library/devops-app:v2
kubectl delete pod node-debugger-desktop-control-plane-*
kubectl rollout restart deployment/devops-app-blue deployment/devops-app-green
```

# Entregable 2: Monitoreo y alertas

La app expone métricas Prometheus en `GET /metrics`:

| Métrica | Tipo | Descripción |
|---|---|---|
| `notes_created_total` | Counter | Notas creadas desde que arrancó el proceso |
| `notes_total` | Gauge | Cantidad de notas guardadas actualmente |
| `http_request_duration_seconds` | Histogram | Llamadas por `method`, `endpoint` y `status` |

La alerta `MuchasNotasCreadas` (`monitoring/alerts.yml`) se dispara cuando
se crean más de 10 notas (X) en una ventana de 5 minutos (Y):

```
sum(increase(notes_created_total[5m])) > 10
```

Para cambiar X o Y, editar esa expresión.

## Opción A: Docker Compose

```bash
docker compose up -d --build
```

| Servicio | URL |
|---|---|
| App | http://localhost:8000 |
| Prometheus | http://localhost:9091 (Status > Targets) |
| Grafana | http://localhost:3001 (admin / admin), dashboard "Notes API" |

Prometheus toma el target `app:8000/metrics` de `monitoring/prometheus.yml`.
Grafana provisiona el datasource y el dashboard desde `monitoring/grafana/`.

Para disparar la alerta:

```bash
for i in $(seq 1 12); do curl -s -X POST http://localhost:8000/add/nota$i > /dev/null; done
```

Y verla en http://localhost:9091/alerts (estado `firing`).

## Opción B: Kubernetes

Se despliega junto a la app de Blue/Green. Hay que reconstruir las imágenes
(para que incluyan `/metrics`) y aplicar los manifiestos:

```bash
docker build -t devops-app:v1 .
docker build -t devops-app:v2 .
kubectl apply -f k8s/blue-deployment.yaml -f k8s/green-deployment.yaml -f k8s/service.yaml
./deploy-monitoring.sh
```

Prometheus descubre cada pod de la app (blue y green) por su label
`app=devops-app`, así que cada réplica es un target propio.

- Prometheus: http://localhost:9091
- Grafana: http://localhost:3001 (admin / admin)

Los datos de Prometheus viven en el PersistentVolumeClaim `prometheus-data`
(2Gi), por lo que sobreviven a reinicios del pod. En Compose se usa el volumen
nombrado `prometheus-data` (se borra con `docker compose down -v`).

No levantar Compose y Kubernetes a la vez, usan los mismos puertos.

# Entregable 3: DevSecOps

Se agregan controles de seguridad sobre el código, la imagen, Kubernetes y el
tiempo de ejecución. Todos los resultados están en `reports/`.

| Reporte | Contenido |
|---|---|
| `reports/npm-audit.txt` | `npm audit` (no aplica) y `pip-audit` sobre `requirements.txt` |
| `reports/semgrep.txt` | Análisis estático con Semgrep |
| `reports/trivyreport.txt` | Escaneo de la imagen `devops-app:v2` con Trivy |
| `reports/kubelinter.txt` | KubeLinter sobre `k8s/`, `kyverno/policies` y el pod conforme |
| `reports/kyverno-test.txt` | Rechazo de un pod no conforme y aceptación de uno conforme |
| `reports/falco-event.log` | Alerta de Falco por una shell interactiva en un pod |

## Seguridad en el código

**npm audit.** El proyecto es Python/FastAPI y no tiene `package.json` ni
lockfile, por lo que `npm audit` termina con `ENOLOCK`. Ese resultado real se
guarda en `reports/npm-audit.txt` junto con el equivalente del ecosistema,
`pip-audit`, que no encuentra vulnerabilidades conocidas.

**Semgrep.** Reglas `p/default`, `p/python`, `p/dockerfile` y `p/kubernetes`:

```bash
docker run --rm -v "$PWD:/src" semgrep/semgrep semgrep scan \
  --config p/default --config p/python --config p/dockerfile --config p/kubernetes \
  --metrics=off --exclude reports /src
```

El primer análisis dio 12 hallazgos, todos de configuración. Se corrigieron:

| Hallazgo | Corrección |
|---|---|
| `missing-user` (Dockerfile) | Usuario `app` (uid 10001) y `USER 10001:10001` |
| `run-as-non-root` | `runAsNonRoot: true` a nivel de pod en los 4 Deployments |
| `allow-privilege-escalation-no-securitycontext` | `allowPrivilegeEscalation: false` y `capabilities.drop: [ALL]` |
| `writable-filesystem-container` | `readOnlyRootFilesystem: true` con `emptyDir` en `/data` (app), `/var/lib/grafana` y `/tmp` (Grafana) |

Resultado final: 0 hallazgos. No se mantuvo ninguna alerta.

## Seguridad en la imagen

```bash
docker build -t devops-app:v2 .
trivy image devops-app:v2 > reports/trivyreport.txt
```

Cambios aplicados al Dockerfile y a las dependencias:

- Dependencias actualizadas (`fastapi 0.162.0`, `uvicorn 0.54.0`, `prometheus-client 0.26.0`).
  Antes del cambio, `starlette 0.38.6` tenía múltiples avisos y `certifi` uno CRITICAL.
- `apt-get upgrade` en la construcción para tomar los parches del sistema base.
- `pip`, `setuptools` y `wheel` se desinstalan al final: solo se necesitan para
  instalar, y sus dependencias vendorizadas (`urllib3`, `msgpack`) traían 5 HIGH/CRITICAL.
- El proceso corre como usuario sin privilegios.

Estado: 0 CRITICAL y 44 HIGH, todas del sistema base Debian 13 y todas con
estado `affected` (Debian aún no publicó versión corregida). Resumen:

| CVE | Paquetes | Decisión |
|---|---|---|
| CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | util-linux (`mount`, `login`, `bsdutils`, `libmount1`, etc.) | Aceptada. Requieren montar filesystems o usar `nsenter`/`mount` con privilegios; el contenedor corre sin root, sin capabilities y con `allowPrivilegeEscalation: false`. |
| CVE-2026-16742 | libsystemd0, libudev1 | Aceptada. Afecta a `systemd-homed`, que no existe en el contenedor. |
| CVE-2026-54369 | libacl1 | Aceptada. Requiere escritura local con privilegios sobre rutas; el filesystem raíz es de solo lectura. |
| CVE-2025-69720 | ncurses | Aceptada. La app no usa ncurses ni una terminal interactiva. |
| CVE-2026-9538 | perl-base | Aceptada. Denegación de servicio con un tar manipulado; la app no usa Perl ni `Archive::Tar`. |

Revisar de nuevo cuando Debian publique parches (`docker build --no-cache`).

## Seguridad en Kubernetes

### Kyverno

Instalación (v1.19.2) y políticas:

```bash
kubectl create -f https://github.com/kyverno/kyverno/releases/download/v1.19.2/install.yaml
kubectl apply -f kyverno/policies/
```

| Política | Archivo | Regla |
|---|---|---|
| `disallow-latest-tag` | `kyverno/policies/disallow-latest-tag.yaml` | Exige etiqueta explícita y prohíbe `latest` |
| `require-requests-limits` | `kyverno/policies/require-resources.yaml` | Exige requests y limits de cpu y memory |
| `disallow-root-containers` | `kyverno/policies/disallow-root.yaml` | Exige `runAsNonRoot: true` y prohíbe `runAsUser: 0` |

Las tres están en modo `Enforce` y excluyen `kube-system`, `kyverno`,
`local-path-storage` y `falco` (Falco necesita `privileged`).

Validación (resultado completo en `reports/kyverno-test.txt`):

```bash
kubectl apply -f kyverno/test/pod-no-conforme.yaml   # rechazado por las tres políticas
kubectl apply -f kyverno/test/pod-conforme.yaml      # aceptado
```

Los Deployments de la app, Prometheus y Grafana se ajustaron para cumplir las
políticas (usuario no root, requests/limits, tags fijos). Se redesplegaron
sin errores con las políticas activas.

### KubeLinter

```bash
docker run --rm -v "$PWD:/src" stackrox/kube-linter lint /src/k8s /src/kyverno/policies /src/kyverno/test/pod-conforme.yaml
```

Resultado: sin errores. Se mantiene una excepción documentada con la anotación
`ignore-check.kube-linter.io/no-anti-affinity` en los Deployments blue y green:
el cluster de Docker Desktop tiene un solo nodo, por lo que la anti-afinidad
entre réplicas no tiene efecto.

## Seguridad en tiempo de ejecución: Falco

Falco 0.45.1 (chart 9.2.1) con driver `modern_ebpf` (el kernel de Docker
Desktop incluye BTF). El manifiesto renderizado está en `falco/falco.yaml` y
los valores en `falco/values.yaml`.

```bash
kubectl create namespace falco
kubectl apply -n falco -f falco/falco.yaml
```

Acción sospechosa y verificación:

```bash
kubectl exec -it deploy/devops-app-blue -- /bin/bash
kubectl -n falco logs ds/falco -c falco | grep 'Shell interactiva'
```

En este runtime (containerd dentro de kind) la regla por defecto
`Terminal shell in container` no dispara con `kubectl exec`, porque su macro
`container_entrypoint` no coincide con el proceso padre. Por eso se agregó en
`falco/values.yaml` la regla `Shell interactiva en contenedor (kubectl exec)`,
que usa la misma condición sin esa macro. La alerta quedó registrada en
`reports/falco-event.log`.
