import { useState } from "react";

import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { useJobPolling } from "../../hooks/useJobPolling";
import { BenchmarkLabView } from "./BenchmarkLabView";

export function RecessionNetLab() {
  const { state, submit } = useJobPolling("recessionnet_kaggle");
  const [seed, setSeed] = useState(0);
  const [maxEpochs, setMaxEpochs] = useState(200);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="RECESSIONNET"
        description="Recession classification on real Kaggle-sourced US macro indicators: base rate, logistic regression, a classical MLP, and a hybrid quantum classifier."
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
            validation_split_date: "2001-01-01",
            test_split_date: "2008-01-01",
            bootstrap_resamples: 500,
          })
        }
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Max epochs" value={maxEpochs} onChange={setMaxEpochs} step={10} min={1} />
          </>
        }
        payloadKey="recessionnet_kaggle"
        metricField="brier_score"
        metricLabel="Brier score"
      />
    </div>
  );
}
