// The deal on screen: sixteen tiles, each a button. A turned or matched tile shows its symbol.
import { Button } from "@karni/ui";
import type { Deal } from "./tiles";

export function TileGrid({ current, onTurn }: { current: Deal; onTurn: (index: number) => void }) {
    return (
        <div className="grid max-w-md grid-cols-4 gap-2" data-testid="tiles">
            {current.tiles.map((symbol, index) => {
                const shown = current.open[index] === true || current.turned.includes(index);
                return (
                    <Button
                        key={index}
                        variant={current.open[index] ? "secondary" : "outline"}
                        className="aspect-square h-auto text-2xl"
                        aria-label={shown ? `Tile ${index + 1}: ${symbol}` : `Tile ${index + 1}`}
                        data-testid={`tile-${index}`}
                        onClick={() => onTurn(index)}
                    >
                        {shown ? symbol : ""}
                    </Button>
                );
            })}
        </div>
    );
}
