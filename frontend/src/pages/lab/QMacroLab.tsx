import { useState } from "react";

import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { useJobPolling } from "../../hooks/useJobPolling";
import { BenchmarkLabView } from "./BenchmarkLabView";

export function QMacroLab() {
  const { state, submit } = useJobPolling("qmacro");
  const [seed, setSeed] = useState(0);
  const [maxEpochs, setMaxEpochs] = useState(200);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Q-MACRO"
        description="h-months-ahead market-factor regression: AR(3), linear regression, a classical MLP, and a hybrid quantum regressor, on real Kenneth French factor data."
      />
      <BenchmarkLabView
        state={state}
        onRun={() =>
          submit({
            seed,
            max_epochs: maxEpochs,
            patience: 20,
            window: 6,
            horizon: 6,
            ar_order: 3,
            validation_split_date: "1988-01-01",
            test_split_date: "2000-01-01",
            bootstrap_resamples: 500,
            feature_series_ids: ["FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF"],
            target_series_id: "FF3_Mkt-RF",
          })
        }
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Max epochs" value={maxEpochs} onChange={setMaxEpochs} step={10} min={1} />
          </>
        }
        payloadKey="qmacro"
        metricField="mase"
        metricLabel="MASE"
      />
    </div>
  );
}
