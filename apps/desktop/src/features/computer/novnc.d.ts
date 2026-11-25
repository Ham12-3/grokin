// noVNC ships no types. This covers the part of the RFB client the Screen tab uses.
declare module "@novnc/novnc" {
  interface RfbOptions {
    shared?: boolean;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RfbOptions);
    viewOnly: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    focusOnClick: boolean;
    disconnect(): void;
    focus(): void;
  }
}
