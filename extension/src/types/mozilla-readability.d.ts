declare module "@mozilla/readability" {
  export type ReadabilityArticle = {
    title: string;
    textContent: string;
  };

  export class Readability {
    constructor(document: Document);
    parse(): ReadabilityArticle | null;
  }
}
