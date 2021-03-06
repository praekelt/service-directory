import logging

from UniversalAnalytics import Tracker
from django.conf import settings
from django.db.models.query import Prefetch
from django.http import Http404
from go_http import HttpApiSender
from rest_framework import status
from rest_framework.generics import RetrieveAPIView, ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from service_directory.api.haystack_elasticsearch_raw_query.\
    custom_elasticsearch import ConfigurableSearchQuerySet
from service_directory.api.models import Keyword, Category, Organisation
from service_directory.api.serializers import\
    HomePageCategoryKeywordGroupingSerializer, \
    KeywordSerializer, OrganisationSummarySerializer, \
    OrganisationSerializer, OrganisationIncorrectInformationReportSerializer, \
    OrganisationRatingSerializer, OrganisationSendSMSRequestSerializer, \
    OrganisationSendSMSResponseSerializer, SearchSerializer

google_analytics_tracker = Tracker.create(
    settings.GOOGLE_ANALYTICS_TRACKING_ID,
    client_id='SERVICE-DIRECTORY-API'
)


def send_ga_tracking_event(path, category, action, label):
    try:
        google_analytics_tracker.send(
            'event',
            path=path,
            ec=category,
            ea=action,
            el=label
        )
    except:
        logging.warn("Google Analytics call failed", exc_info=True)


class HomePageCategoryKeywordGrouping(APIView):
    """
    Retrieve keywords grouped by category for the home page
    ---
    GET:
        response_serializer: HomePageCategoryKeywordGroupingSerializer
    """
    def get(self, request):
        filtered_keyword_queryset = Keyword.objects.filter(
            show_on_home_page=True
        )

        home_page_categories_with_keywords = Category.objects.filter(
            show_on_home_page=True
        ).prefetch_related(
            Prefetch(
                'keyword_set',
                queryset=filtered_keyword_queryset,
                to_attr='filtered_keywords'
            )
        )

        # exclude categories that don't have any keywords associated
        home_page_categories_with_keywords = [
            category for category in home_page_categories_with_keywords
            if category.filtered_keywords
        ]

        serializer = HomePageCategoryKeywordGroupingSerializer(
            home_page_categories_with_keywords, many=True
        )
        return Response(serializer.data)


class KeywordList(ListAPIView):
    """
    List keywords, optionally filtering by category
    ---
    GET:
        parameters:
            - name: category
              type: string
              paramType: query
              allowMultiple: true
    """
    serializer_class = KeywordSerializer

    def get_queryset(self):
        queryset = Keyword.objects.all()

        category_list = self.request.query_params.getlist('category')

        show_on_home_page = self.request.query_params.get(
            'show_on_home_page')
        if show_on_home_page:
            queryset = queryset.filter(show_on_home_page=True)

        if category_list:
            queryset = queryset.filter(categories__name__in=category_list)

            if queryset:
                # although this endpoint accepts a list of categories we only
                # send a tracking event for the first one as generally only one
                # will be supplied (and we don't want to block the response
                # because of a large number of tracking calls)
                send_ga_tracking_event(
                    self.request._request.path, 'View', 'KeywordsInCategory',
                    category_list[0]
                )

        return queryset


class Search(APIView):
    """
    Search for organisations by search term and/or location.
    If location coordinates are supplied then results are ordered ascending
    by distance.
    ---
    GET:
        parameters:
            - name: search_term
              type: string
              paramType: query
            - name: location
              description: latitude,longitude
              type: string
              paramType: query
            - name: place_name
              description: only used for analytics purposes
              type: string
              paramType: query
            - name: radius
              description:
               limit response to user location within this radius (KMs)
              type: integer
              paramType: query
              default: None
            - name: country
              description: filter response to the given country iso code
              type: string
              paramType: query
              default: None
            - name: keywords[]
              description: filter response to the given category keywords
              type: array[string]
              paramType: query
              default: None
            - name: categories[]
              description: filter response to the given categories
              type: array[integer]
              paramType: query
              default: None
            - name: all_categories
              description: filter response all categories
              type: boolean
              paramType: query
              default: None
        response_serializer: OrganisationSummarySerializer
    """
    def get(self, request):
        search_serializer = SearchSerializer(data=request.query_params)

        send_ga_tracking_event(
            request._request.path, 'Search',
            request.query_params.get('search_term', ''),
            request.query_params.get('place_name', '')
        )

        # perform search
        if search_serializer.is_valid():
            sqs = ConfigurableSearchQuerySet().models(Organisation)
            sqs = search_serializer.load_search_results(sqs)
            serializer = OrganisationSummarySerializer(
                search_serializer.format_results(sqs), many=True)
            return Response(serializer.data)
        return Response(search_serializer.errors)


class OrganisationDetail(RetrieveAPIView):
    """
    Retrieve organisation details
    """
    queryset = Organisation.objects.all()
    serializer_class = OrganisationSerializer

    def get(self, request, *args, **kwargs):
        response = super(OrganisationDetail, self).get(
            request, *args, **kwargs
        )

        if response and response.data:
            try:
                organisation_name = response.data['name']
                send_ga_tracking_event(
                    request._request.path,
                    'View',
                    'Organisation',
                    organisation_name
                )
            except (KeyError, TypeError):
                logging.warn("Did not find expected data in response to make"
                             " Google Analytics call", exc_info=True)

        return response


class OrganisationReportIncorrectInformation(APIView):
    """
    Report incorrect information for an organisation
    ---
    POST:
         serializer: OrganisationIncorrectInformationReportSerializer
    """
    def post(self, request, *args, **kwargs):
        organisation_id = int(kwargs.pop('pk'))

        try:
            organisation = Organisation.objects.get(id=organisation_id)
        except Organisation.DoesNotExist:
            raise Http404

        serializer = OrganisationIncorrectInformationReportSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)
        serializer.save(organisation=organisation)

        send_ga_tracking_event(
            request._request.path,
            'Feedback',
            'OrganisationIncorrectInformationReport',
            organisation.name
        )

        return Response(serializer.data,
                        status=status.HTTP_201_CREATED)


class OrganisationRate(APIView):
    """
    Rate the quality of an organisation
    ---
    POST:
         serializer: OrganisationRatingSerializer
    """
    def post(self, request, *args, **kwargs):
        organisation_id = int(kwargs.pop('pk'))

        try:
            organisation = Organisation.objects.get(id=organisation_id)
        except Organisation.DoesNotExist:
            raise Http404

        serializer = OrganisationRatingSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)
        serializer.save(organisation=organisation)

        send_ga_tracking_event(
            request._request.path,
            'Feedback',
            'OrganisationRating',
            organisation.name
        )

        return Response(serializer.data,
                        status=status.HTTP_201_CREATED)


class OrganisationSendSMS(APIView):
    """
    Send an SMS to a supplied cell_number with a supplied organisation_url
    ---
    POST:
         request_serializer: OrganisationSendSMSRequestSerializer
         response_serializer: OrganisationSendSMSResponseSerializer
    """
    def post(self, request, *args, **kwargs):
        request_serializer = OrganisationSendSMSRequestSerializer(
            data=request.data
        )

        request_serializer.is_valid(raise_exception=True)

        analytics_label = ''

        try:
            sender = HttpApiSender(
                settings.VUMI_GO_ACCOUNT_KEY,
                settings.VUMI_GO_CONVERSATION_KEY,
                settings.VUMI_GO_API_TOKEN,
                api_url=settings.VUMI_GO_API_URL
            )

            if 'your_name' in request_serializer.validated_data:
                message = '{0} has sent you a link: {1}'.format(
                    request_serializer.validated_data['your_name'],
                    request_serializer.validated_data['organisation_url']
                )
                analytics_label = 'send'
            else:
                message = 'You have sent yourself a link: {0}'.format(
                    request_serializer.validated_data['organisation_url']
                )
                analytics_label = 'save'

            sender.send_text(
                request_serializer.validated_data['cell_number'],
                message
            )

            response_serializer = OrganisationSendSMSResponseSerializer(
                data={'result': True}
            )
        except:
            logging.error("Failed to send SMS", exc_info=True)
            response_serializer = OrganisationSendSMSResponseSerializer(
                data={'result': False}
            )

        send_ga_tracking_event(
            request._request.path,
            'SMS',
            request_serializer.validated_data['organisation_url'],
            analytics_label
        )

        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data,
                        status=status.HTTP_200_OK)
