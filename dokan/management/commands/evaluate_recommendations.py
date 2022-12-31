from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand

from dokan.intelligence import _fit_collaborative_model
from dokan.models import Item, OrderItem


class Command(BaseCommand):
    help = (
        "Offline evaluation of the item-based collaborative-filtering recommender: "
        "leave-one-out hit-rate@k against historical order baskets, compared to a "
        "simple popularity baseline."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--k",
            type=int,
            default=4,
            help="Number of recommendations considered a 'hit' if they contain the held-out item.",
        )

    def handle(self, *args, **options):
        k = options["k"]

        basket_rows = OrderItem.objects.filter(ordered=True).values_list("orders__id", "item_id")
        baskets: dict[int, set[int]] = {}
        for order_id, item_id in basket_rows:
            if order_id is None or item_id is None:
                continue
            baskets.setdefault(order_id, set()).add(item_id)

        eval_baskets = {
            order_id: items for order_id, items in baskets.items() if len(items) >= 2
        }

        if len(eval_baskets) < 3:
            self.stdout.write(
                self.style.WARNING(
                    "Not enough multi-item order history to evaluate "
                    f"(found {len(eval_baskets)} usable baskets, need at least 3). "
                    "Run migrations (0011_seed_recommendation_training_data) to load "
                    "training data first."
                )
            )
            return

        collaborative_model = _fit_collaborative_model()
        if collaborative_model is None:
            self.stdout.write(self.style.WARNING("Collaborative model could not be fitted."))
            return

        purchase_counts = Counter()
        for items in baskets.values():
            purchase_counts.update(items)
        popularity_ranking = [item_id for item_id, _ in purchase_counts.most_common()]

        cf_hits = 0
        popularity_hits = 0
        total_cases = 0

        for items in eval_baskets.values():
            for held_out_item in items:
                context_items = items - {held_out_item}
                if not context_items:
                    continue
                total_cases += 1

                scores: dict[int, float] = {}
                for context_item in context_items:
                    context_position = collaborative_model.index.get(context_item)
                    if context_position is None:
                        continue
                    for candidate_id, candidate_position in collaborative_model.index.items():
                        if candidate_id in context_items:
                            continue
                        similarity = float(
                            collaborative_model.similarity[context_position, candidate_position]
                        )
                        if similarity > scores.get(candidate_id, 0.0):
                            scores[candidate_id] = similarity

                cf_top_k = [
                    item_id
                    for item_id, _ in sorted(scores.items(), key=lambda entry: -entry[1])[:k]
                ]
                if held_out_item in cf_top_k:
                    cf_hits += 1

                popularity_top_k = [
                    item_id for item_id in popularity_ranking if item_id not in context_items
                ][:k]
                if held_out_item in popularity_top_k:
                    popularity_hits += 1

        if total_cases == 0:
            self.stdout.write(self.style.WARNING("No evaluable leave-one-out cases were found."))
            return

        cf_hit_rate = cf_hits / total_cases
        popularity_hit_rate = popularity_hits / total_cases
        lift = (
            ((cf_hit_rate - popularity_hit_rate) / popularity_hit_rate * 100.0)
            if popularity_hit_rate > 0
            else float("inf") if cf_hit_rate > 0 else 0.0
        )

        self.stdout.write(self.style.SUCCESS("Recommendation engine evaluation"))
        self.stdout.write(f"Evaluated {total_cases} leave-one-out cases from {len(eval_baskets)} baskets.")
        self.stdout.write(f"Catalog size: {Item.objects.count()} items")
        self.stdout.write("")
        self.stdout.write(f"{'Model':<30}{'Hit-rate@' + str(k):>15}")
        self.stdout.write(f"{'Item-based collaborative filtering':<30}{cf_hit_rate:>15.2%}")
        self.stdout.write(f"{'Popularity baseline':<30}{popularity_hit_rate:>15.2%}")
        self.stdout.write("")
        if lift == float("inf"):
            self.stdout.write(self.style.SUCCESS("CF model beats the popularity baseline (baseline scored 0%)."))
        else:
            direction = "beats" if lift >= 0 else "trails"
            self.stdout.write(
                self.style.SUCCESS(f"CF model {direction} the popularity baseline by {lift:+.1f}%.")
            )
