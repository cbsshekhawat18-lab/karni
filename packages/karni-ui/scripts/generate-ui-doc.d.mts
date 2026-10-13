export interface UiManifest {
  components: string[];
  hooks: string[];
  roles: Record<string, string>;
}
export function render(manifest: UiManifest): string;
