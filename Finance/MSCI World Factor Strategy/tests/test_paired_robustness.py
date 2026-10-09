"""Independent invariants for fee timing and paired conditional resampling."""
import numpy as np
import pandas as pd
import pytest
from factor_portfolio.paired_robustness import fee_calendar, stationary_draws, validate_protocol
from factor_portfolio.publication_reproduce import check_robustness


def test_regular_anniversary_has_no_duplicate_terminal_fee():
    dates=pd.bdate_range('2020-01-03','2020-02-03')
    events=fee_calendar(dates,.0005)
    assert len(events)==1
    assert events.iloc[0].payment_kind=='regular_month'
    assert events.iloc[0].event_date==pd.Timestamp('2020-02-03')
    assert events.iloc[0].proposed_fund_fee_fraction==.0005/12


def test_weekend_payment_stub_starts_from_actual_payment_not_nominal_date():
    dates=pd.bdate_range('2020-01-31','2020-03-03')
    events=fee_calendar(dates,.0005)
    assert list(events.event_date)==[pd.Timestamp('2020-03-02'),pd.Timestamp('2020-03-03')]
    assert list(events.payment_kind)==['regular_month','terminal_stub']
    assert events.iloc[1].stub_calendar_days==1
    assert events.iloc[1].proposed_fund_fee_fraction==.0005/365.2425


def test_identical_pair_preserves_zero_gap_in_every_resample():
    log=np.array([.01,-.02,.03,-.04,.05])
    draws=stationary_draws(np.column_stack([log,log]),[.999,.999],2.,3,150,41)
    np.testing.assert_array_equal(draws[:,0],draws[:,1])


def test_opening_cost_is_counted_once_and_never_resampled():
    draws=stationary_draws(np.zeros((25,2)),[.99,.98],2.,4,100,42)
    expected=np.broadcast_to(np.sqrt([.99,.98])-1,draws.shape)
    np.testing.assert_allclose(draws,expected,atol=1e-15,rtol=0)


def test_fixed_seed_reproduces_every_draw():
    pair=np.arange(50,dtype=float).reshape(25,2)/1000
    np.testing.assert_array_equal(stationary_draws(pair,[.999,.998],3.,4,100,77),
                                  stationary_draws(pair,[.999,.998],3.,4,100,77))


@pytest.mark.parametrize('annual_fee',[float('nan'),-1,float('inf')])
def test_invalid_fee_rejected(annual_fee):
    with pytest.raises(ValueError):fee_calendar(pd.bdate_range('2020-01-03',periods=3),annual_fee)


def test_protocol_change_rejected_before_simulation(tmp_path):
    p=tmp_path/'changed.json';p.write_text('{}')
    with pytest.raises(ValueError,match='frozen robustness protocol differs'):
        validate_protocol(tmp_path,p)


def test_new_run_identity_cannot_override_changed_robustness_results(tmp_path):
    import hashlib,json
    p=tmp_path/'config';p.mkdir();(p/'paired_robustness_protocol_2026-10-09.json').write_text('protocol')
    output=tmp_path/'study';output.mkdir();data=output/'matrix.csv';data.write_text('gap\n1\n')
    digest=hashlib.sha256(data.read_bytes()).hexdigest()
    manifest=dict(status='complete',run_id='new',figures_included=False,configuration_snapshots={},artifacts={'matrix.csv':digest})
    (output/'run_manifest.json').write_text(json.dumps(manifest))
    ref=dict(protocol_sha256=hashlib.sha256(b'protocol').hexdigest(),configuration_snapshots={},artifacts_sha256={'matrix.csv':'different'})
    (p/'paired_robustness_reference_2026-10-09.json').write_text(json.dumps(ref))
    with pytest.raises(ValueError,match='paired study results differ'):
        check_robustness(tmp_path,output)
