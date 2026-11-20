/**
 * Experimental. `<FamilyHome>`: `/` in a project of parts.
 *
 * - **Staff** (a role beyond `customer`): the home tiles of their roles,
 *   which every installed part contributes (`GET /dashboard/`, karni.tiles):
 *   the shop's orders to send, commerce's revenue, a CRM's deals to follow.
 * - **A visitor or a customer**: the public home a part registered (the
 *   shop's storefront, `registerPublicHome`). Without one, a customer sees
 *   their own tiles and a visitor is asked to sign in.
 *
 * The empty state says what to do: with no part installed, how to add one;
 * with parts but no tile for the role, where tiles come from.
 *
 * Escape hatch: `tiles` rewrites the tiles before they render, `empty`
 * replaces the empty state, and a project writes its own home page.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { DashboardTiles, type DashboardTileDef } from "../dashboard/dashboard-tiles";
import { EmptyState } from "../empty-state/empty-state";
import { Page } from "../page/page";
import { Button } from "../primitives/button";
import { useAudience, useSiteName, type Audience } from "./audience";
import { publicHome } from "./registry";

export interface FamilyHomeProps {
  /** The router's push: a tile's link, the sign-in. */
  navigate: (to: string) => void;
  /** The parts the project holds (`PARTS` of the build's parts.ts), for the empty state. */
  parts?: readonly string[];
  /** The page's heading for staff. Default "Home". */
  title?: string;
  /** A line under the heading. */
  description?: string;
  /** Rewrites the tiles before they render. */
  tiles?: (tiles: readonly DashboardTileDef[]) => readonly DashboardTileDef[];
  /** Replaces the empty state. */
  empty?: React.ReactNode;
  /** Who is looking (default: from the signed-in person's roles). */
  audience?: Audience;
  siteName?: string;
  className?: string;
}

function command(name: string): React.ReactElement {
  return <code className="rounded bg-muted px-1 py-0.5 font-mono text-sm">{name}</code>;
}

/** Experimental. The empty home: what to install, or where a role's tiles come from. */
export function FamilyEmptyHome({
  parts = [],
  audience,
  navigate,
}: {
  parts?: readonly string[];
  audience: Audience;
  navigate: (to: string) => void;
}): React.ReactElement {
  if (parts.length === 0) {
    return (
      <EmptyState
        title="Nothing is installed yet"
        description={
          <>
            Add a part to this project, for example {command("karni recipes add shop")} or{" "}
            {command("karni recipes add booking")}. Its screens join the menu and its tiles for each
            role show here.
          </>
        }
      />
    );
  }
  if (audience === "staff") {
    return (
      <EmptyState
        title="No tiles for your roles yet"
        description="Each installed part puts what a role should see first here. Ask an admin for the role you work in, or use the menu."
      />
    );
  }
  return (
    <EmptyState
      title="Welcome"
      description="Your orders, bookings and details are on your account page."
      action={<Button onClick={() => navigate("/account")}>Your account</Button>}
    />
  );
}

/** Experimental. `/`: the tiles of staff, the public home for everyone else. */
export function FamilyHome({
  navigate,
  parts,
  title = "Home",
  description,
  tiles,
  empty,
  audience: fixed,
  siteName,
  className,
}: FamilyHomeProps): React.ReactElement | null {
  const found = useAudience();
  const audience = fixed ?? found;
  const name = useSiteName(siteName);
  if (audience === "loading") return null;
  const Public = publicHome()?.component;
  if (audience !== "staff" && Public !== undefined) return <Public />;
  if (audience === "visitor") {
    return (
      <Page title={name || title} className={className}>
        <EmptyState
          title="Sign in to continue"
          description="Sign in with your email to see your home."
          action={<Button onClick={() => navigate("/signin?next=%2F")}>Sign in</Button>}
        />
      </Page>
    );
  }
  return (
    <Page title={title} description={description} className={cn(className)}>
      <DashboardTiles
        onOpen={navigate}
        {...(tiles !== undefined ? { tiles } : {})}
        empty={empty ?? <FamilyEmptyHome parts={parts} audience={audience} navigate={navigate} />}
      />
    </Page>
  );
}
