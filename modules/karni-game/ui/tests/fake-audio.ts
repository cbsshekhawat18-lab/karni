/** A small stand-in for AudioContext: enough graph to test what @karni/game asks of it. */
export class FakeParam {
  value = 1;
  /** Every automation call, in order: `["linear", 0.3, 1.5]` is a ramp to 0.3 ending at 1.5 s. */
  calls: [string, number, number?][] = [];
  setTargetAtTime(value: number): void {
    this.value = value;
  }
  setValueAtTime(value: number, at: number): void {
    this.calls.push(["set", value, at]);
    this.value = value;
  }
  linearRampToValueAtTime(value: number, at: number): void {
    this.calls.push(["linear", value, at]);
    this.value = value;
  }
  cancelScheduledValues(at: number): void {
    this.calls.push(["cancel", at]);
  }
}

export class FakeNode {
  connections: FakeNode[] = [];
  connect(node: FakeNode): void {
    this.connections.push(node);
  }
}

export class FakeGain extends FakeNode {
  gain = new FakeParam();
}

export class FakeSource extends FakeNode {
  buffer: unknown = null;
  loop = false;
  playbackRate = { value: 1 };
  started = false;
  stopped = false;
  onended: (() => void) | null = null;
  start(): void {
    this.started = true;
  }
  stop(): void {
    this.stopped = true;
    this.onended?.();
  }
}

export class FakeAudioContext {
  state: "suspended" | "running" | "closed" = "suspended";
  currentTime = 0;
  destination = new FakeNode();
  sources: FakeSource[] = [];
  gains: FakeGain[] = [];
  refuseResume = false;
  createGain(): FakeGain {
    const gain = new FakeGain();
    this.gains.push(gain);
    return gain;
  }
  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
  createBuffer(): object {
    return {};
  }
  async resume(): Promise<void> {
    if (this.refuseResume) throw new Error("not allowed");
    this.state = "running";
  }
  async suspend(): Promise<void> {
    this.state = "suspended";
  }
  async decodeAudioData(data: ArrayBuffer): Promise<{ bytes: number }> {
    return { bytes: data.byteLength };
  }
}
