# 중앙 EKS Argo CD의 GKE 등록 인계

## 필요한 이유

GitOps [#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)에서 GKE 배포 기반을 준비해요. `sample-app-gcp`는 중앙 EKS Argo CD에서 관리하는 모델이고 `destination.name: tokyo-gke`를 재사용해요. 선언된 이름만으로 실제 클러스터 등록·접근·인증이 완료되지는 않아요.

## 대상과 GCP 준비

- 프로젝트 `crystal-sbh2026-gcp-1009`, GKE `tokyo-gke`, `asia-northeast1-a`
- API `https://34.146.143.116`, kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`
- amd64 노드 1대, `e2-standard-2`, Kubernetes `1.35.8-gke.1225000`
- GCP 준비 파일: [GKE bootstrap](../argocd/install/gke/README.md), 설치와 권한은 GCP 담당이 적용해요.
- 앱 namespace는 `sample-app`, Kubernetes SA 후보는 `sample-app/argocd-deployer`예요. namespace 조회와 현재 Service·Rollout·AnalysisTemplate 쓰기에 제한돼요. 역할 subject는 합의할 실제 인증 주체에 맞춰요.
- 현재 GKE API에는 작업 PC `/32`만 허용돼요. 전체 Google Cloud 외부 IP 허용은 꺼져 있어요. EKS 송신 주소가 확인되면 GCP 담당이 기존 접근을 보존하면서 추가해요.
- 운영 종료 목표: 2026-10-12 23:59 KST, 사용자가 수동 삭제해요.

## EKS 담당에게 필요한 작업

- Controller와 server에서 GKE API로 나가는 실제 egress IPv4/고정 경로를 확인해 주세요. 노드 public IP나 NAT 주소를 추측하지 않고 실제 실행 경로로 확인해 주세요.
- GCP 인증 주체·공급 경로·실제 만료/갱신 방식과 담당을 맞춰 주세요. GCP bootstrap은 운영 토큰·Google 키를 생성하지 않았어요. 개인 OAuth 토큰 복사는 사용하지 않아요.
- EKS `argocd`의 등록 이름 `tokyo-gke`·namespace 제한 `sample-app`·`clusterResources: "false"`·CA/TLS 검증을 구성해 주세요. 실제 토큰/키는 Git·Slack·일반 로그에 남기지 않아요.
- UID를 읽는 클러스터 전역 권한은 앱 SA에 주지 않았어요. GCP 운영자 UID 확인과, EKS에서 namespace 안 리소스/UID를 대조하는 방식으로 실제 대상을 확인해 주세요.
- bootstrap과 인증/등록 검증 이후 GCP Application을 적용해 주세요. 현재 작성 중인 변경은 아직 main에 없으므로 적용 파일·revision은 GCP 담당과 맞춰 주세요. `CreateNamespace=false`이고 namespace는 GCP에서 준비해요.
- GCP 기존 알림 구독은 GCP Application 파일만 수정해요. 공통 Notifications 템플릿/새 실패 트리거와 카나리 분석은 성진님 담당 변경을 재사용해요.

## 검증 기준

- EKS 실제 실행 경로에서 TCP 443·CA/호스트 검증·GCP API 인증이 성공해요.
- `tokyo-gke`가 위 GKE를 가리키고 관리 범위가 `sample-app`에 제한돼요. 인증 만료·갱신과 장애 복구 조건을 기록해요.
- 실제 GKE Rollout·Pod Ready·내부 `/healthz`·`/api/info`와 `gcp/asia-northeast1`·이미지/앱 버전까지 확인해요. Synced만으로 완료하지 않아요.
- 중앙 GCP Notifications와 Review API 배포 기록을 확인해요. 외부 LB·후속 카나리·GCP 검토/baseline·전체 환경 gate는 후속 완료 항목과 구분해요.
- 기존 AWS/local Application의 목적지·기존 AWS 알림·ESO Secret 공급에 예상하지 못한 변경이 없어요.

이 문서는 직접 보내지 않은 인계 요청문이에요. 이 채팅은 EKS 등록 Secret·Controller·IAM·네트워크를 수정하지 않아요.
