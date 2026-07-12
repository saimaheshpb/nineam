from dataclasses import dataclass, field
from app.services.embeddings import calculate_similarity

CLUSTER_SIZE_WEIGHT = 3
SOURCE_DIVERSITY_WEIGHT = 2

@dataclass()
class ArticleForClustering:
    id: int
    source_name: str
    headline: str
    url: str
    embedding: list[float]
    importance_score: int


@dataclass
class StoryCluster:
    articles: list[ArticleForClustering] = field(default_factory=list)

    def add_article(self, article: ArticleForClustering) -> None:
        self.articles.append(article)

    def best_similarity(self, article: ArticleForClustering) -> float:
        if not self.articles:
            return 0.0
        scores = [
            calculate_similarity(article.embedding, existing.embedding)
            for existing in self.articles
        ]

        return max(scores)

    @property
    def size(self) -> int:
        return len(self.articles)

    @property
    def representative_headline(self) -> str:
        if not self.articles:
            return "Untitled Cluster"

        return self.articles[0].headline

    @property
    def rank_score(self) -> float:
        if not self.articles:
            return 0.0

        cluster_size_score = self.size * CLUSTER_SIZE_WEIGHT

        average_importance = sum(
            article.importance_score for article in self.articles
        ) / self.size

        unique_sources = len({
            article.source_name for article in self.articles
        })

        source_diversity_score = unique_sources * SOURCE_DIVERSITY_WEIGHT

        return cluster_size_score + average_importance + source_diversity_score


def cluster_articles(
        articles: list[ArticleForClustering],
        similarity_threshold: float = 0.72,
) -> list[StoryCluster]:
    clusters: list[StoryCluster] = []
    for article in articles:
        best_cluster = None
        best_score = 0

        for cluster in clusters:
            score = cluster.best_similarity(article)

            if score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster is not None and best_score >= similarity_threshold:
            best_cluster.add_article(article)
        else:
            new_cluster = StoryCluster()
            new_cluster.add_article(article)
            clusters.append(new_cluster)

    clusters.sort(key=lambda cluster: cluster.rank_score, reverse=True)

    return clusters
