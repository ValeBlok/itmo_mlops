{{- define "mlops-search.name" -}}
{{- printf "%s-mlops-search" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Selector labels: используются только Deployment и Service. */}}
{{- define "mlops-search.selectorLabels" -}}
app.kubernetes.io/name: mlops-search
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "mlops-search.labels" -}}
{{ include "mlops-search.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/*
Immutable image digest. Пустой или некорректный digest останавливает рендер.
*/}}
{{- define "mlops-search.imageDigest" -}}
{{- $digest := required "image.digest is required: pass --set image.digest=sha256:<64 hex>" .Values.image.digest | toString | trim -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
{{- fail (printf "image.digest must be sha256:<64 lowercase hex chars>, got %q" $digest) -}}
{{- end -}}
{{- $digest -}}
{{- end -}}

{{/*
Runtime image только в форме repository@sha256:digest. Mutable tags запрещены.
*/}}
{{- define "mlops-search.image" -}}
{{- if .Values.image.tag -}}
{{- fail "image.tag is not supported: deploy by immutable image.digest only" -}}
{{- end -}}
{{- $repo := required "image.repository is required" .Values.image.repository | toString | trim -}}
{{- if or (contains "@" $repo) (regexMatch ":[^/]*$" $repo) -}}
{{- fail (printf "image.repository must not contain a tag or digest, got %q" $repo) -}}
{{- end -}}
{{- printf "%s@%s" $repo (include "mlops-search.imageDigest" .) -}}
{{- end -}}

{{- define "mlops-search.rankingMode" -}}
{{- $mode := .Values.rankingMode | toString -}}
{{- if not (has $mode (list "normal" "reverse")) -}}
{{- fail (printf "rankingMode must be normal or reverse, got %q" $mode) -}}
{{- end -}}
{{- $mode -}}
{{- end -}}
