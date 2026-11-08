# Runbook Search API: production delivery assignment

Вы подключились к команде платформы, которая выпускает внутренний сервис поиска по инженерной базе знаний. Это очень важно, так как хороший поиск ускоряет реализацию решений - разработчик не тратит время на просмотр нерелевантных статей. Приложение уже имеет рабочий API и воспроизводимый retrieval-модуль, но цепочка поставки не завершена. Ваша задача — довести сервис до безопасного деплоя в Kubernetes: от проверки качества модели до promotion и rollback.

Можно использовать публичный GitLab с GitLab CI или публичный GitHub с GitHub Actions. Код и container image могут быть публичными; kubeconfig и токены — никогда.

## Продукт

`Runbook Search API` — внутренний retrieval-сервис для operational runbook’ов. При запуске он загружает согласованный индекс из immutable image и не обращается к внешним ML API.

Основной контракт:

- `POST /v1/search` — поиск с `request_id`, latency, версией индекса и scored results;
- `GET /v1/documents/{id}/recommendations` — похожие документы;
- `GET /livez` и `GET /readyz` — раздельные Kubernetes probes;
- `GET /meta` — build, image, environment и model metadata;
- `GET /metrics` — Prometheus exposition;
- `/docs` — OpenAPI UI.

В сервисе есть JSON access logs, сквозной `X-Request-ID`, непривилегированный runtime, read-only root filesystem и ресурсные ограничения. Retrieval-модель — CPU-only hybrid TF-IDF по словам и символьным n-граммам с cosine ranking. Это хороший baseline для компактной корпоративной базы знаний: он быстрый, объяснимый и не требует GPU.

## Что находится в репозитории

- `app/` — FastAPI и retrieval engine;
- `data/` — корпус runbook’ов и evaluation set;
- `scripts/build_index.py` — сборка versioned model artifact;
- `scripts/evaluate.py` — MRR и Recall@3 quality gate;
- `scripts/verify_release.py` — внешний semantic smoke test;
- `tests/` — API и platform contract tests;
- `Dockerfile` — намеренно незавершенная multi-stage сборка;
- `helm/mlops-search/` — chart с намеренной ошибкой image policy;
- `.gitlab-ci.yml` и `.github/workflows/ci-cd.yml` — заготовки delivery pipeline;
- `compose.yaml` и `Makefile` — локальная среда.

## Предоставленный Kubernetes

У вас уже есть выданный преподавателем доступ к стенду с K8s, используйте его.

| Параметр | Значение |
|---|---|
| Namespace | `mlops-students` |
| Helm storage driver | `configmap` |
| Reference staging | `search-staging` |
| Reference production | `search-prod` |
| Reference image | `docker.io/devijoe/runbook-search-api@sha256:8d6a1923c981bfc56ffa2f1f6f31868dc442fda834acac664ad1f7be174250bb` |

Общий kubeconfig не требует личной учетной записи Yandex и имеет только namespaced RBAC. Нельзя создавать namespaces, CRD, ClusterRole, LoadBalancer и NodePort. Не меняйте reference releases и releases других команд.

Проверьте доступ:

```bash
export KUBECONFIG=/path/to/mlops-students.kubeconfig
export HELM_DRIVER=configmap
kubectl auth can-i get pods -n mlops-students
kubectl get deploy,svc -n mlops-students
helm list -n mlops-students
```

Посмотреть reference API:

```bash
kubectl -n mlops-students port-forward svc/search-staging-mlops-search 18080:80
curl -s http://127.0.0.1:18080/meta | jq
curl -s -X POST http://127.0.0.1:18080/v1/search \
  -H 'content-type: application/json' \
  -H 'x-request-id: acceptance-001' \
  -d '{"query":"как откатить неудачный релиз модели","limit":3}' | jq
```

## Этап 1. Запустить baseline локально

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_index.py --output artifacts
pytest -q
python scripts/evaluate.py --artifact-dir artifacts
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Ожидаемый порог: `MRR >= 0.85`, `Recall@3 >= 0.90`. Отрицательный контроль обязан сформировать отчет и завершиться ненулевым кодом:

```bash
python scripts/evaluate.py --artifact-dir artifacts --ranking-mode reverse
```

## Этап 2. Исправить container packaging

В `Dockerfile` намеренно не перенесен проверенный model artifact из builder в runtime. Image соберется, но сервис не станет ready. Найдите и устраните дефект, затем проверьте полный runtime:

```bash
docker compose up -d --build search
docker compose ps
python3 scripts/smoke_local.py
curl -s http://127.0.0.1:18080/meta | jq
curl -s http://127.0.0.1:18080/metrics
docker compose down
```

Model artifact должен входить в image. Скачивание модели при старте Pod запрещено: код, зависимости и индекс должны продвигаться как единая версия.

## Этап 3. Исправить Helm chart

Deployment намеренно использует mutable `latest`, а digest не валидируется. Доработайте chart:

1. Пустой или некорректный digest должен останавливать `helm template`.
2. Runtime image задается только как `repository@sha256:digest`.
3. Service остается `ClusterIP`.
4. Probes, security context, requests/limits и Helm test должны сохраниться.
5. В `/meta` должны попадать environment, build revision, image digest и index version.

До deployment выполните lint и render:

```bash
helm lint helm/mlops-search \
  --set image.repository=REGISTRY/USER/runbook-search-api \
  --set image.digest=sha256:YOUR_DIGEST

helm template PREFIX-search-staging helm/mlops-search \
  -n mlops-students \
  --set image.repository=REGISTRY/USER/runbook-search-api \
  --set image.digest=sha256:YOUR_DIGEST
```

## Этап 4. Построить CI/CD

Доработайте одну заготовку — GitLab CI или GitHub Actions:

```text
tests -> build index -> quality gate -> negative quality control
      -> build/push image -> resolve digest
      -> staging -> Helm test -> semantic smoke
      -> manual approval -> production -> semantic smoke
```

Обязательные свойства:

- deployment jobs сериализованы через `resource_group` или `concurrency`;
- production защищен manual approval;
- staging и production получают один и тот же digest без пересборки;
- kubeconfig хранится в masked secret `KUBE_CONFIG_B64`;
- задан `HELM_DRIVER=configmap`;
- имена releases содержат выданный преподавателем уникальный префикс;
- `metadata.json` и quality report сохранены как CI artifacts;
- в Git и CI logs отсутствуют credentials.

## Этап 5. Проверить rollback по качеству

Сделайте production upgrade с `rankingMode=reverse`. Процесс и probes останутся healthy, но semantic smoke обнаружит неправильный top result. Delivery job должен сохранить последнюю хорошую revision, выполнить `helm rollback`, повторить smoke и подтвердить восстановление `rankingMode=normal`.

Удалять release и устанавливать заново нельзя: для приемки нужна история revisions.

## Имена и изоляция команд

Если выдан префикс `team07`, используйте только:

- `team07-search-staging`;
- `team07-search-prod`.

Вместо teamX используйте свою фамилию, например  khakimov-search-prod

## Что сдавать

1. URL публичного GitLab/GitHub repository и успешного pipeline.
2. Image repository, tag и неизменяемый digest.
3. Quality report и лог заблокированного reverse-кандидата.
4. `/meta` из staging и production.
5. Deployment image двух окружений с одним digest.
6. `helm history` до и после плохого release.
7. Лог failed semantic smoke, rollback и успешной повторной проверки.
8. Короткий ответ: почему readiness недостаточно для контроля качества ML-сервиса.

## Критерии

| Результат | Баллы |
|---|---:|
| Reproducible model build, tests и quality gate | 25 |
| Production-grade container | 15 |
| Helm и immutable digest | 15 |
| Staging и smoke tests | 15 |
| Promotion одного digest | 10 |
| Проверенный rollback | 15 |
| Secrets hygiene и документация | 5 |

После приемки удалите только releases своей команды:

```bash
helm uninstall team07-search-staging -n mlops-students
helm uninstall team07-search-prod -n mlops-students
```
