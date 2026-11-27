import "@testing-library/jest-dom/vitest";

// jsdom has no canvas: say so quietly (null context) instead of logging "not implemented" noise, so the
// components that probe for a canvas take their fallback path in tests.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
