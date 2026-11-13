// A product's reviews: the approved ones, newest first, and a form for a customer whose
// parcel with it arrived. A new review waits for staff before it shows.
import { problemOf } from "@karni/commerce-ui";
import {
  EmptyState,
  Input,
  Label,
  PendingButton,
  Skeleton,
  Textarea,
  useKarniClient,
  useResourceList,
  useResourceMutations,
} from "@karni/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Rating, Stars } from "./Rating";
import type { Product, Review } from "./types";

interface Eligibility {
  can_review: boolean;
  reason: string;
  status: string | null;
}

const WAITING: Record<string, string> = {
  pending: "Thank you. Your review shows here once the shop approves it.",
  approved: "Thank you for your review.",
  rejected: "The shop did not publish your review.",
};

function ReviewForm({
  product,
  onDone,
}: {
  product: Product;
  onDone: () => void;
}) {
  const { create } = useResourceMutations("reviews");
  const [rating, setRating] = useState(0);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const ids = { rating: useId(), title: useId(), body: useId() };
  return (
    // eslint-disable-next-line karni/no-raw-elements -- a star rating with two fields, posted once; ResourceForm has no star input
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          { product: product.id, rating, title, body },
          { onSuccess: onDone },
        );
      }}
    >
      <h3 className="font-semibold">Review {product.name}</h3>
      <fieldset className="space-y-1">
        <legend id={ids.rating} className="text-sm font-medium">
          Your rating
        </legend>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((star) => (
            <label key={star} className="cursor-pointer">
              {/* eslint-disable-next-line karni/no-raw-elements -- each star is a radio, drawn as a star */}
              <input
                type="radio"
                name={ids.rating}
                value={star}
                checked={rating === star}
                onChange={() => setRating(star)}
                className="peer sr-only"
              />
              <span
                aria-hidden="true"
                className={`rounded px-1 text-2xl peer-focus-visible:ring-2 peer-focus-visible:ring-ring ${
                  rating >= star ? "text-primary" : "text-muted-foreground/40"
                }`}
              >
                ★
              </span>
              <span className="sr-only">
                {star} {star === 1 ? "star" : "stars"}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.title}>Title (optional)</Label>
        <Input
          id={ids.title}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.body}>Your review</Label>
        <Textarea
          id={ids.body}
          required
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
      </div>
      {create.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {problemOf(create.error)}
        </p>
      ) : null}
      <PendingButton
        type="submit"
        pending={create.isPending}
        disabled={rating === 0}
      >
        Send the review
      </PendingButton>
    </form>
  );
}

export function Reviews({ product }: { product: Product }) {
  const client = useKarniClient();
  const queries = useQueryClient();
  const list = useResourceList<Review>("reviews", {
    filters: { product: product.id, status: "approved" },
    ordering: "-created_at",
    pageSize: 10,
  });
  const key = ["shop", "review-eligibility", product.id];
  const eligibility = useQuery<Eligibility>({
    queryKey: key,
    queryFn: ({ signal }) =>
      client.request<Eligibility>("/reviews/eligibility/", {
        query: { product: product.id },
        signal,
      }),
  });
  const reviews = list.data?.results ?? [];
  return (
    <section
      aria-labelledby="reviews-heading"
      className="space-y-4 border-t border-border pt-6"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id="reviews-heading" className="text-xl font-semibold">
          Reviews
        </h2>
        <Rating average={product.rating_average} count={product.rating_count} />
      </div>
      {eligibility.data?.can_review ? (
        <ReviewForm
          product={product}
          onDone={() => void queries.invalidateQueries({ queryKey: key })}
        />
      ) : eligibility.data?.status ? (
        <p role="status" className="text-sm text-muted-foreground">
          {WAITING[eligibility.data.status] ?? ""}
        </p>
      ) : eligibility.data?.reason ? (
        <p className="text-sm text-muted-foreground">
          {eligibility.data.reason}
        </p>
      ) : null}
      {list.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : reviews.length === 0 ? (
        <EmptyState
          title="No reviews yet"
          description="Customers review what they bought once it reaches them."
        />
      ) : (
        <ul className="space-y-4">
          {reviews.map((review) => (
            <li
              key={review.id}
              className="space-y-1 rounded-lg border border-border p-4"
            >
              <p className="flex flex-wrap items-center gap-2">
                <Stars value={review.rating} />
                <span className="sr-only">{review.rating} out of 5</span>
                {review.title ? <strong>{review.title}</strong> : null}
              </p>
              <p className="whitespace-pre-line">{review.body}</p>
              <p className="text-sm text-muted-foreground">
                {review.author_name}
                {review.verified ? ", bought it here" : ""},{" "}
                {new Date(review.created_at).toLocaleDateString()}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
