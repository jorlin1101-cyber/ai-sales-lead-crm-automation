from lead_cleaner.schemas.lead import LeadProcessingResult, RawLeadInput
from lead_cleaner.rag.retriever import RagRetriever
from lead_cleaner.services.cleaning import clean_lead
from lead_cleaner.services.feature_extractor import FeatureExtractor
from lead_cleaner.services.lead_analyzer import analyze_lead
from lead_cleaner.services.rag_grounding import ground_analysis_with_rag
from lead_cleaner.services.recommendation_generator import RecommendationGenerator
from lead_cleaner.services.validation import validate_lead


def process_lead(
    raw_lead: RawLeadInput,
    feature_extractor: FeatureExtractor | None = None,
    rag_retriever: RagRetriever | None = None,
    recommendation_generator: RecommendationGenerator | None = None,
) -> LeadProcessingResult:
    cleaned_lead = clean_lead(raw_lead)
    validation_result = validate_lead(cleaned_lead)

    if not validation_result.is_valid:
        return LeadProcessingResult(
            cleaned_lead=cleaned_lead,
            validation_result=validation_result,
            analysis_result=None,
        )

    analysis_result = analyze_lead(
        cleaned_lead,
        feature_extractor=feature_extractor,
    )
    grounded_analysis, sources = ground_analysis_with_rag(
        analysis_result,
        cleaned_lead,
        rag_retriever=rag_retriever,
        recommendation_generator=recommendation_generator,
    )

    return LeadProcessingResult(
        cleaned_lead=cleaned_lead,
        validation_result=validation_result,
        analysis_result=grounded_analysis,
        sources=sources,
    )
