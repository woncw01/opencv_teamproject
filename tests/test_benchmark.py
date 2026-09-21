"""C unit tests; synthetic timing samples are not experimental performance."""
import time
import pytest
from src.benchmark import summarize_metrics, measure, generate_plots, evaluate_events


def test_fps_and_stats():
    rows = [dict(completed_at=t, measurement_start_at=0, measurement_end_at=3,
                 analyzed=True, read_ms=v) for t, v in [(1, 1), (2, 2), (3, 3)]]
    s = summarize_metrics(rows)
    assert s['throughput_fps'] == 1
    assert s['mean_fps'] == 1
    assert s['std_fps'] == 0
    assert s['read_ms_mean'] == 2
    assert s['read_ms_median'] == 2
    assert s['read_ms_std'] == pytest.approx((2/3)**0.5)
    assert s['read_ms_p95'] == pytest.approx(2.9)


def test_measure_on_exception():
    row = {}
    with pytest.raises(RuntimeError):
        with measure(row, 'detect'):
            raise RuntimeError('test')
    assert row['detect_ms'] >= 0


def test_no_data_plots(tmp_path):
    assert generate_plots(tmp_path/'missing.csv', tmp_path) == []
    assert not list(tmp_path.glob('*.png'))


def test_one_to_one_matching():
    truth = [dict(video_name='v', zone_name='z', start_time=1, end_time=5, event_type='intrusion')]
    ev = [dict(zone_name='z', start_time=2, alert_time=3, end_time=4)] * 2
    s = evaluate_events(truth, ev, video_name='v')
    assert s['detected_events'] == 1
    assert s['false_alarms'] == 1
    assert s['false_alarm_rate'] == .5
    assert s['mean_alert_delay_s'] == 2
    with pytest.raises(ValueError, match='Mock'):
        evaluate_events(truth, ev, video_name='v', mock=True)


def test_plot_measured_mock_data(tmp_path):
    from src.benchmark import write_table
    # Deterministic unit-test inputs only; all files remain in pytest temp directory.
    rows=[]
    for mode in ('baseline','threaded','optimized'):
        row=dict(source='TEST_ONLY', resolution='64x48', pipeline_mode=mode, variant='standard',
                 throughput_fps=1.0, experiment_kind='throughput', mock=True, run_status='completed')
        from src.benchmark import STAGES
        row.update({s+'_ms_mean':1.0 for s in STAGES})
        rows.append(row)
    path=tmp_path/'summary.csv'
    write_table(path,rows,list(rows[0]))
    files=generate_plots(path,tmp_path)
    assert {p.name for p in files} == {'fps_comparison.png','stage_latency.png','optimization_comparison.png'}
    assert all(p.stat().st_size>0 for p in files)


def test_suite_matrix(monkeypatch, tmp_path):
    from src import benchmark, pipeline
    source=tmp_path/'TEST_ONLY.file'
    source.write_text('not decoded; orchestration test')
    calls=[]
    monkeypatch.setattr(pipeline, 'run_pipeline', lambda source, mode, config: calls.append((mode, config)))
    monkeypatch.setattr(benchmark, 'generate_plots', lambda *args: [])
    benchmark.run_suite(str(source), {}, mock=True, no_display=True)
    assert len(calls)==27
    assert {tuple(c['input_resolution']) for _,c in calls}=={(640,480),(1280,720),(1920,1080)}
    assert all(c['duration_seconds']==60 and c['loop_video'] for _,c in calls)
    assert len({c['suite_id'] for _,c in calls})==1
    with pytest.raises(ValueError):
        benchmark.run_suite(str(source), {}, seconds=10)


def test_skip_drop_and_warmup_stats():
    rows=[dict(completed_at=i+1,measurement_start_at=1,measurement_end_at=4,
               analyzed=i==1,dropped=i==2,warmup=i==0) for i in range(4)]
    s=summarize_metrics(rows)
    assert s['input_frames']==3
    assert s['analyzed_frames']==1
    assert s['throughput_fps']==pytest.approx(1/3)
    assert s['drop_rate']==pytest.approx(1/3)
    assert s['skip_rate']==pytest.approx(1/3)


def test_failed_and_mixed_graphs(tmp_path):
    from src.benchmark import write_table
    row=dict(source='TEST',resolution='64x48',pipeline_mode='baseline',variant='standard',
             throughput_fps=1,experiment_kind='throughput',mock=True,run_status='failed')
    path=tmp_path/'summary.csv'
    write_table(path,[row],list(row))
    assert generate_plots(path,tmp_path)==[]
    row['run_status']='completed'
    write_table(path,[row,{**row,'mock':False}],list(row))
    with pytest.raises(ValueError,match='Separate'):
        generate_plots(path,tmp_path)
