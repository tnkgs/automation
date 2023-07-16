# Standard Library
from typing import List, TypedDict

# Third Party Library
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.v14 import (
    GenerateKeywordIdeasRequest,
    GoogleAdsServiceClient,
    KeywordPlanIdeaServiceClient,
    KeywordPlanNetworkEnum,
    KeywordSeed,
)


class SuggestKeyword(TypedDict):
    text: str
    avg_monthly_searches: int
    competition: str


def get_suggest_keywords(
    client: GoogleAdsClient, target_keywords: List[str]
) -> List[SuggestKeyword]:
    if client.login_customer_id is None:
        raise ValueError("login_customer_id is not set.")

    keyword_plan_idea_service: KeywordPlanIdeaServiceClient = (
        client.get_service("KeywordPlanIdeaService")
    )

    # ja
    language = GoogleAdsServiceClient.language_constant_path("1005")

    # JP Hino
    # geo_target_constant = GoogleAdsServiceClient.geo_target_constant_path(
    #     "1009288"
    # )

    keyword_plan_network = (
        KeywordPlanNetworkEnum.KeywordPlanNetwork.GOOGLE_SEARCH_AND_PARTNERS
    )

    keyword_seed = KeywordSeed(keywords=target_keywords)

    request = GenerateKeywordIdeasRequest(
        customer_id=client.login_customer_id,
        keyword_plan_network=keyword_plan_network,
        language=language,
        geo_target_constants=[],
        include_adult_keywords=False,
        keyword_seed=keyword_seed,
    )

    response = keyword_plan_idea_service.generate_keyword_ideas(
        request=request,
    )

    keywords: List[SuggestKeyword] = []
    for result in response:
        competition = result.keyword_idea_metrics.competition.name
        avg_monthly_searches = result.keyword_idea_metrics.avg_monthly_searches

        keywords.append(
            {
                "text": result.text,
                "avg_monthly_searches": avg_monthly_searches,
                "competition": competition,
            }
        )
    return keywords
