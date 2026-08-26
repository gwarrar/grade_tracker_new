import { Composition } from "remotion";

import { OVERVIEW_DURATION, OVERVIEW_FPS, Overview } from "./Overview";

export function RemotionRoot() {
  return (
    <Composition
      id="Overview"
      component={Overview}
      durationInFrames={OVERVIEW_DURATION}
      fps={OVERVIEW_FPS}
      width={1920}
      height={1080}
    />
  );
}
