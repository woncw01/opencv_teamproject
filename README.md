# 작업장 위험 구역 감시 및 실시간 영상 처리 최적화

Python/OpenCV로 작업장 다각형 위험 구역의 움직임을 감시하고, 같은 영상으로 순차 처리·멀티스레드·최적화 성능을 비교하는 5일 팀 프로젝트입니다. **현재는 초기 구조와 인터페이스 설계 단계**입니다. 실제 안전 시스템으로 검증하지 않았으며 감지·경고·녹화·측정은 아직 구현되지 않았습니다.

## 문제 정의와 목표

움직이는 물체의 위험 구역 침입을 검출하고 N프레임 연속 감지 후 경고합니다. 사건 전 3초부터 경고 해제 후 5초까지 원본 영상을 보존하며 발생 시각·지속 시간·구역 이름을 CSV로 남깁니다. 동일 입력과 판정 기준에서 FPS, 경고 지연, 오경보·미검출을 함께 비교합니다. 외부 AI 검출 모델은 필수가 아니며 MOG2 배경 차분과 외곽선을 사용합니다. 사람 식별이나 객체 추적은 기본 범위에 포함하지 않습니다.

## 핵심 기능과 아키텍처

```text
main → pipeline → utils (입력·설정)
                → zones (구역 로드)
                → preprocess → detect → 원본 좌표 복원 → detect.check_intrusion
                → state → 사건 CSV (pipeline 책임)
                → recorder (원본 영상 저장만)
                → benchmark (측정 원자료·집계)
                → 메인 스레드 화면 표시
```

`pipeline.analyze_frame` 하나가 세 버전에서 같은 `preprocess_frame`, `detect_motion`, `check_intrusion`을 호출합니다. 알고리즘을 버전별로 복제하지 않습니다.

| 버전 | 실행 구조 | 적용 설정 |
|---|---|---|
| baseline | 읽기→전처리→움직임→침입→상태→표시/저장 순차 | 원본 해상도, 전체 화면, 매 프레임 |
| threaded | 입력 worker→제한 Queue→메인 분석/표시/저장 | baseline과 동일 분석 설정 |
| optimized | threaded 구조 + 선택적 최적화 | analysis_resolution, roi_enabled, frame_interval |

baseline/threaded에서는 ROI=False, 분석 크기=원본, 간격=1로 유효 설정을 구성할 예정입니다. 출력 기능과 MOG2·침입 기준·N·해제 기준은 동일합니다. 유효 설정은 실행별 결과에 저장합니다. `--preview`는 기존 그레이스케일 데모이며 Baseline 성능으로 사용하지 않습니다.

## 전체 폴더와 책임

현재 작업 디렉터리를 프로젝트 루트로 사용합니다. 별도의 중첩 project_name 폴더를 만들지 않습니다.

```text
team_project/
├── README.md
├── requirements.txt
├── config.json
├── .gitignore
├── check_env.py                       # 기존 환경 점검 보존
├── src/
│   ├── main.py
│   ├── utils.py
│   ├── preprocess.py
│   ├── detect.py
│   ├── zones.py
│   ├── state.py
│   ├── recorder.py
│   ├── pipeline.py
│   └── benchmark.py
├── data/
│   ├── samples/                       # 실행 시 생성, Git 제외
│   └── SOURCES.md
├── results/                           # 실행 시 생성, Git 제외
└── docs/
    ├── 수행계획서.md
    ├── 실험기록.md
    └── 최종보고서.md
```

기존 교육용 HTML과 `:Zone.Identifier` 파일도 그대로 보존합니다. `src`는 Python namespace package로 실행하므로 `__init__.py`를 추가하지 않았습니다.

| 파일 | 담당 | 책임 / 추가 이유 |
|---|---|---|
| main.py | B | CLI, 설정 기본 검사, 출력 폴더 준비, 실행 진입 |
| utils.py | 공통 | 기존 이미지 I/O, 입력, FPS, JSON 유틸리티; 구현·시그니처 보존 |
| preprocess.py | A | 전처리·축소·좌표 복원 |
| detect.py | A | MOG2 움직임 및 위험 구역 침입 판정만 |
| zones.py | A | 추가: 다각형 편집·JSON I/O를 감지와 분리 |
| state.py | A | 추가: 구역별 연속 감지와 상태 전이를 감지와 분리 |
| recorder.py | B | 추가: 시간 버퍼와 영상 저장 수명 관리를 분리; CSV·침입 판정 금지 |
| pipeline.py | B | 추가: 공통 분석 경로, 실행 방식, 사건 CSV 조립 |
| benchmark.py | C | 추가: 측정 정의와 통계/CSV를 감지와 분리 |
| config.json | 공통 | 초기 실험 설정 |
| requirements.txt | 공통 | 기존 패키지 버전 유지 |
| check_env.py | 공통 | 기존 버전·이미지 저장 점검; 설명만 추가 |
| data/SOURCES.md | 공통 | 영상 출처·촬영·권한 기록 |
| docs/수행계획서.md | 공통 | 일정·역할·완료 기준 |
| docs/실험기록.md | C | 실행별 조건과 실제 측정 기록 |
| docs/최종보고서.md | C | 병목·성능·정확도 분석 |
| README.md / .gitignore | 공통 | 개발 계약·사용 안내 / 영상 및 환경 파일 제외 |

## 함수 인터페이스와 데이터 계약

모든 새 기능은 `NotImplementedError` 스텁입니다. 상세 매개변수, 반환 타입, 순서, 경계 조건은 각 함수 docstring을 기준으로 구현합니다. 기존 공통 함수 변경이 필요하면 이유·호출부 영향을 설명하고 팀 합의 후 적용합니다.

| 함수 | 입력 → 출력 |
|---|---|
| preprocess_frame | 원본 ndarray, 설정, 선택 ROI → 분석 ndarray, 변환 dict |
| restore_boxes | 분석 박스, 변환 dict → 원본 박스 목록 |
| create_background_subtractor | 설정 dict → MOG2 객체 |
| detect_motion | 분석 ndarray, MOG2, 분석 면적 기준 → (x,y,w,h) 목록 |
| check_intrusion | 원본 박스, 구역 목록 → dict[str,bool] |
| edit_zones / save_zones / load_zones | 원본 영상 → 구역 목록 / 경로·구역·크기 → None / 경로·크기 → 구역 목록 |
| update_state | 상태 dict, 감지 dict 또는 None, 원본 index, 영상 초, 설정 → 새 상태 dict, 전이 목록 |
| create_recorder | 설정, 원본 FPS, 원본 크기 → 녹화 세션 dict |
| record_frame / close_recorder | 세션·원본 영상·영상 초·전이 / 세션 → 종료 클립 메타데이터 목록 |
| analyze_frame | 원본 영상, MOG2, 구역, 유효 설정 → 구역별 bool |
| run_pipeline | source str, mode str, config dict → 종료 코드 int |
| summarize_metrics / write_metrics | 표본 목록 → 통계 dict / 경로·표본 목록 → None |
| main / process | CLI → 종료 코드 / 기존 BGR 영상 → 그레이스케일 BGR 영상 |

- 영상: `np.ndarray`, H×W×3, uint8 BGR. 녹화는 원본 크기·원본 시간축을 유지합니다.
- 박스는 (x,y,w,h), 다각형은 원본 좌표 [[x,y], ...]. 침입은 박스 **하단 중앙점**, 경계를 포함합니다. 최소 면적 200은 원본 픽셀 면적이며 축소 시 scale_x×scale_y를 곱합니다.
- ROI는 전체 위험 구역의 합집합을 포함하는 단일 bounding rectangle로 시작합니다. 여러 ROI별 MOG2 복제는 하지 않습니다. crop/해상도가 바뀌면 MOG2를 초기화합니다.
- 구역 JSON 계약: `{"schema_version":1,"frame_size":[1280,720],"zones":[{"name":"위험구역 A","points":[[100,100],[400,100],[400,400]]}]}`. 예시일 뿐 실제 구역 파일은 미생성입니다. 최소 3개 꼭짓점, 비영 면적, 자기 교차 금지, 이름 유일, 해상도 일치가 필요합니다.
- 상태 dict: `{zone_name: {status, hit_count, clear_count, last_frame_index, last_media_time_s, event_id, alert_time_s}}`. 전이 dict: `{type: "alert"|"cleared", event_id: str, zone_name: str, frame_index: int, media_time_s: float, duration_s: float|None}`. 사건 ID는 실행 ID+구역+순번으로 유일하게 만듭니다. alert의 duration_s는 None입니다.
- IDLE→DETECTING→ALERT→CLEARED. N=1이면 즉시 ALERT, DETECTING에서 False면 IDLE. ALERT에서 clear_frames 연속 False면 CLEARED. CLEARED는 다음 분석에서 새 감지를 시작합니다. 구역별 독립 상태입니다.
- **N은 연속된 원본 프레임의 성공 판정 횟수**입니다. 미분석(None)이나 원본 index 공백은 hit/clear 카운터를 초기화하고 ALERT 자체는 유지합니다. 생략 프레임을 직전 True로 채우지 않습니다. 따라서 frame_interval>1은 N>1에서 경고를 막을 수 있습니다. 최초 최적화 비교는 간격=1, 간격 조정은 정확도 저하를 포함하는 별도 실험으로 표시합니다. 이 의미를 바꾸려면 팀 합의가 필요합니다.
- 파일 영상 시간은 FPS가 유효한 경우 원본 index/FPS, 가변 FPS는 검증된 PTS를 사용합니다. 카메라는 수집 monotonic 경과 시간입니다. 성능 시간은 perf_counter, 실제 처리 발생 시각은 timezone 포함 ISO 8601로 따로 기록합니다. 업로드 파일의 촬영 시각을 추정하지 않습니다.

## 스레드·큐·녹화 계약

Queue packet은 `{frame_index, media_time_s, captured_at, frame}`이며 captured_at은 perf_counter 초입니다. 모든 프레임을 분석하지 않아도 recorder에는 원본 프레임을 순서대로 전달해야 합니다. 기본 `queue_policy=block`은 bounded Queue의 backpressure로 프레임을 보존합니다. `put/get` timeout, stop Event, EOF sentinel, worker 예외 전달, finally release/join을 구현합니다. imshow/waitKey 및 구역 편집은 메인 스레드에서만 실행합니다.

`drop_oldest`는 향후 지연 실험용 예약 값입니다. 입력 시점 별도 원본 보존 경로와 사건 시각 동기화, 지연된 경고를 받을 수 있는 버퍼를 구현하기 전에는 거부해야 합니다. 드롭 수·원본 index 공백·녹화 무결성을 기록하며 block 실험과 분리합니다. 카메라는 block만으로 장치 내부 유실을 막을 수 없으므로 공정한 기본 비교는 파일을 사용합니다.

녹화는 alert 기준 이전 pre_seconds를 포함하고 ALERT 동안 지속하며 **cleared 이후 post_seconds**에 종료합니다. 여러 구역·재침입이 겹치면 클립을 병합하고 event_id 목록으로 연결합니다. 시작 시점에 3초가 없거나 EOF에서 5초가 없으면 확보한 만큼 저장하고 truncated=True로 기록합니다. EOF 시 미해제 사건은 CSV status=open_at_eof, duration_s는 빈칸으로 남깁니다. 원본 FPS 불명·writer 실패·메모리 한계는 명시적으로 처리합니다. deque에는 copy를 저장하고 영상 시각으로 오래된 프레임을 제거합니다. 메모리 예상값은 너비×높이×3×FPS×pre_seconds 바이트에 큐 비용을 더합니다.

## 환경 설정 및 실행

프로젝트 루트에서 Python **3.10** 환경을 권장합니다. 기존 고정 패키지는 OpenCV contrib 4.10.0.84, NumPy 1.26.4, Pandas 2.2.2, Matplotlib 3.8.4입니다. Threading/Queue/Collections는 표준 라이브러리입니다. 기존 check_env의 3.9 안내와 달리 고정 NumPy/Matplotlib 조합에는 3.10을 사용하세요.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python check_env.py
python -m src.main --help
python -m src.main --source data/samples/test.mp4 --mode baseline --dry-run
python -m src.main --source data/samples/test.mp4 --preview
```

`--help`, `--dry-run`은 초기 CLI 기능입니다. dry-run은 일부 설정 검사·폴더 생성만 하며 영상·구역의 존재나 전체 설정 스키마를 검증하지 않습니다. preview는 기존 실제 그레이스케일 화면 기능이며 영상 파일과 GUI 환경이 필요합니다. `q`로 종료합니다. 기존 `python src/main.py` 진입도 보존합니다. 기존 utils의 숫자 카메라 경로는 Windows CAP_DSHOW를 사용하므로 Linux 카메라 지원은 후속 TODO입니다.

아래는 **파서가 지원하지만 감시 동작은 미구현**인 명령어입니다. 현재 안내 후 종료 코드 2를 반환합니다. 기본 mode는 baseline입니다.

```bash
python -m src.main --source data/samples/test.mp4
python -m src.main --source data/samples/test.mp4 --mode baseline
python -m src.main --source data/samples/test.mp4 --mode threaded
python -m src.main --source data/samples/test.mp4 --mode optimized
```

`--config config.json`으로 설정 파일을 선택합니다. source CLI가 config의 source보다 우선합니다. config 파일 기본 위치는 프로젝트 루트이며 설정 안의 상대 경로·출력 경로는 실행 작업 디렉터리 기준입니다. 항상 프로젝트 루트에서 실행하세요. 구역 편집 CLI는 후속 구현 대상입니다.

## 테스트 영상 준비

허가받은 고정 카메라 영상을 `data/samples/test.mp4`에 직접 준비하고 data/SOURCES.md를 작성합니다. 비침입·짧은 침입·N프레임 이상 침입·구역 경계·다중 구역·조명 변화·EOF 직전 사건을 포함합니다. 영상 해시, FPS, 해상도, 수동 침입 시작/종료 프레임을 기록합니다. 실제 영상·구역은 포함하지 않았습니다. data/samples와 results는 Git 제외이며 main 실행 시 자동 생성합니다.

## 설정값 설명

기본값은 초기 실험 제안이며 검증된 최적값이 아닙니다. 아직 감시 스텁에 적용되지 않습니다.

| 키 | 기본값 | 의미와 조정 방법 |
|---|---|---|
| source | data/samples/test.mp4 | 입력 파일 또는 숫자 카메라 문자열; CLI 우선 |
| zones_path | data/zones.json | 원본 해상도와 일치하는 구역 JSON |
| mog2.history | 500 | 배경 학습 길이; 환경 변화에 맞춰 조정 |
| mog2.var_threshold | 16.0 | 배경 구분 임계값; 오경보/미검출 함께 확인 |
| mog2.detect_shadows | true | 그림자 구분; 127은 움직임 마스크에서 제외 |
| min_area | 200 | 원본 픽셀 최소 외곽선 면적; 해상도·작은 객체 고려 |
| blur_kernel | 5 | 양의 홀수 블러 커널; 작은 객체 손실 주의 |
| canny_low / canny_high | 50 / 150 | 기존 키 보존, MOG2 설계에서 사용하지 않음 |
| consecutive_frames | 5 | 경고 진입 연속 원본 프레임 수; 1 이상 |
| clear_frames | 10 | 경고 해제 연속 비침입 원본 프레임 수; 1 이상 |
| pre_seconds / post_seconds | 3.0 / 5.0 | 사전 버퍼 / 해제 후 녹화 초; 0 이상 |
| analysis_resolution | [640,360] | optimized 분석 최대 [너비,높이], 양의 정수; 종횡비 유지 |
| roi_enabled | false | optimized에서 전체 구역을 포함한 crop 활성화 |
| queue_max_size | 8 | threaded/optimized 큐 크기; 메모리·대기 시간 함께 조정 |
| queue_policy | block | 프레임 보존 기본; drop_oldest는 선행 구현 필요 |
| frame_interval | 1 | optimized 분석 간격; 1은 모든 프레임, N 계약 제약 확인 |
| measure_fps | true | benchmark 수집 활성화; 기존 preview FPS와 별개 |
| warmup_frames | 30 | 성능 집계 제외 원본 프레임 수; MOG2 학습은 수행 |

전체 스키마·범위 검사와 mode별 유효 설정 생성은 pipeline 초기화 TODO입니다.

## 최적화 실험 및 결과 파일

같은 영상·구역·MOG2 초기화·판정 기준·경고/녹화/표시 설정·warm-up으로 비교합니다. 먼저 baseline, 다음 threaded, 이후 ROI만, 해상도만, 간격만, 큐 정책만 각각 바꾸고 마지막에 조합합니다. 실험당 최소 3회 반복하고 실행 순서를 교차합니다. 환경(CPU/OS/라이브러리), 원본 해시, 유효 설정, 분석/표시/녹화 프레임 수와 드롭을 기록합니다. GUI/저장 비용도 end-to-end 시간에 포함합니다.

- `throughput_fps` = warm-up 이후 분석 완료 수 / 측정 구간 경과 초. 측정 시작·종료 경계를 원자료에 기록합니다.
- `mean_fps`, `std_fps` = 연속 분석 완료 perf_counter 차이의 역수 표본 평균·모표준편차(ddof=0). 처리량과 혼용하지 않습니다. 표시 FPS는 별도입니다.
- 단계 ms = read, queue_wait, preprocess, detect, intrusion, state, record, display. worker 읽기와 메인 처리는 겹치므로 합계를 전체 시간으로 간주하지 않습니다.
- 경고 지연: 영상 기준 `alert_media_s - 수동 침입 시작 media_s`; 시스템 지연은 `alert_perf_counter - 해당 프레임 captured_at`. 파일 처리 속도로 촬영 당시 벽시계 지연을 추정하지 않습니다. 정답이 없으면 측정 불가로 표기합니다.
- 사건 단위 오경보·미검출은 같은 구역의 정답 구간과 경고 구간의 시간 중첩으로 매칭합니다. 한 정답에 여러 경고가 있으면 중복 경고를 따로 집계하고, 정답 없는 경고는 오경보, 경고 없는 정답은 미검출입니다. warm-up 구간 정답은 제외 여부를 동일하게 명시합니다.

아래 파일들은 **향후 생성 예정**이며 현재 가짜 결과는 만들지 않습니다.

| 경로 | 내용 |
|---|---|
| results/<run_id>/events.csv | event_id, zone_name, occurred_at(시간대 포함 처리 시각), alert_media_s, cleared_media_s, duration_s, status, clip_path |
| results/<run_id>/clips/*.mp4 | 원본 FPS/크기 사건 영상; 사건 ID와 매핑 |
| results/<run_id>/clips.csv | path, event_ids, start_s, end_s, truncated |
| results/<run_id>/metrics.csv | frame_index, media_time_s, captured_at, completed_at, measurement_start_at, measurement_end_at, analyzed, dropped, warmup, 각 단계 *_ms |
| results/<run_id>/summary.json | 처리량·FPS 통계·단계 평균; 미측정은 null |
| results/<run_id>/effective_config.json | 실행 유효 설정, 환경, 영상 해시 |
| results/<run_id>/plots/ | 실제 측정 기반 FPS·단계 비용 비교 그래프 |

metrics rows는 원본 프레임 단위이며 미분석 단계 시간은 빈칸입니다. summarize_metrics는 analyzed=True, warmup=False만 사용하고 완료 시각을 정렬·검증합니다. measurement_start_at/end_at은 해당 집계 구간의 공통 경계입니다. 드롭 표본과 측정 불가 값에 0을 임의로 채우지 않습니다. 사건 CSV는 pipeline, 성능 CSV는 benchmark, 영상만 recorder가 담당합니다.

## 스크린샷 삽입 위치

TODO: 구역 편집 화면 / 경고 발생 화면 / 클립 저장 결과 / 실제 FPS 비교 그래프를 실행 후 삽입합니다. results는 Git 제외이므로 보고서에 포함할 이미지는 검토 후 docs/images/에 별도로 추가하세요.

## 현재 상태와 팀원별 다음 작업

완료: 폴더·설정·문서, 함수 계약과 TODO, CLI 파싱·기본 설정 검사·폴더 생성·미구현 안내. 기존 미리보기와 utils 구현은 보존했습니다. 미완료: 모든 감지·구역 편집·상태·녹화·스레드·최적화·측정·그래프 기능. 실제 감시 성능은 미측정입니다.

1. 공통: 실제 영상·권한·구역 좌표 준비, 인터페이스 검토. B는 전체 설정 검증과 Linux 입력을 검토합니다.
2. A: zones → preprocess → detect → state. 경계점·빈 검출·N=1·해제·다중 구역·미분석을 검증합니다.
3. B: baseline 공통 경로 → recorder 및 사건 CSV. 버퍼 시작/EOF·겹침·writer 실패를 확인합니다.
4. C: benchmark 원자료·집계, 수동 정답, 실험기록을 준비하고 baseline을 실측합니다.
5. B: threaded 종료/예외/큐 → optimized ROI·축소·간격·지연 관리. A와 좌표·상태 의미를 검증합니다.
6. C: 동일 조건 반복 비교, 병목·정확도·지연 분석, 최종보고서 작성. 모든 팀원이 통합 시연합니다.

검증 범위와 실행 결과는 작업 완료 보고에 명시합니다. 카메라·GUI·실제 감시·성능은 해당 환경에서 추가 검증해야 합니다.

### 초기 구조 검증 기록 (2026-09-21)

실행 확인: `compileall` 문법 검사, 모든 Python 모듈/함수 docstring 존재, 설정 로딩, 세 모드 dry-run(코드 0), 세 감시 모드 미구현 안내(코드 2), 기존 직접 실행 dry-run, queue_max_size=0 거부, 폴더 존재, 메모리 영상 그레이스케일 변환, 기존 FPSMeter 기본 호출. 별도 테스트 파일·성능 수치는 생성하지 않았습니다.

미검증: 실제 영상/카메라/GUI 미리보기, 패키지 신규 설치, 모든 감지·상태·녹화·스레드·측정 기능. 현재 `.git`이 유효한 저장소로 인식되지 않아 Git diff/status 기반 검증은 수행하지 못했습니다. 기존 파일은 직접 읽어 확인했으며 utils는 docstring 외 구현을 보존했습니다.

## GitHub 협업 방법

원본 저장소는 [whrjsdnr/opencv_teamproject](https://github.com/whrjsdnr/opencv_teamproject)입니다. 각 팀원은 GitHub에서 원본을 자신의 계정으로 **Fork**한 뒤 개인 Fork를 Clone합니다.

```bash
git clone https://github.com/YOUR_GITHUB_ID/opencv_teamproject.git
cd opencv_teamproject
git remote add upstream https://github.com/whrjsdnr/opencv_teamproject.git
git fetch upstream
git switch -c feature/detection upstream/main
```

`YOUR_GITHUB_ID`는 자신의 계정으로 바꿉니다. A는 `feature/detection`, B는 `feature/pipeline`, C는 `feature/benchmark`에서 개발합니다. 개인 Fork의 브랜치에 Push하고 원본 저장소 main으로 PR을 생성하여 리뷰 후 병합합니다. 원본 main 직접 Push는 최초 등록 이후 사용하지 않습니다.

담당 파일, 최신 main 동기화, Commit 규칙과 PR 템플릿은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요. 위 초기 구조 검증 기록의 Git 상태는 초기 설계 당시의 기록입니다.
