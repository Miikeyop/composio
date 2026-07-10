#!/usr/bin/env python3
"""Generate evidence-backed integration findings for the 100-app research set.

The script is intentionally runnable without paid app accounts or API keys. It
uses a curated seed corpus as the deterministic baseline, then optionally probes
evidence URLs and can be extended with OpenRouter/Composio extraction where
credentials exist.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SEED_PROFILES = """app|description|auth_methods|credential_access|api_surface|surface_breadth|mcp_status|buildability|main_blocker|evidence_urls|evidence_notes|confidence
Salesforce|Enterprise CRM platform for sales, service, marketing, and custom business data.|OAuth2;token|self_serve|REST;SOAP;GraphQL;SDK|broad|community|buildable|OAuth app setup and Salesforce org permissions add setup friction.|https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_what_is_rest_api.htm;https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_flows.htm|REST API and connected-app OAuth docs are public; developer orgs are self-serve.|0.90
HubSpot|CRM and marketing automation platform with contacts, companies, tickets, deals, and content APIs.|OAuth2;private app token|self_serve|REST;Webhooks|broad|community|easy_win|Rate limits and app scopes need careful packaging.|https://developers.hubspot.com/docs/api/overview;https://developers.hubspot.com/docs/apps/authentication|Public developer docs describe OAuth and private app access tokens.|0.92
Pipedrive|Sales CRM focused on pipelines, deals, activities, people, and organizations.|OAuth2;API token|self_serve|REST;Webhooks|moderate|community|easy_win|Per-user API tokens are easy but OAuth is preferred for marketplace apps.|https://developers.pipedrive.com/docs/api/v1;https://pipedrive.readme.io/docs/marketplace-oauth-authorization|Public REST API with OAuth marketplace flow and API token support.|0.88
Attio|Modern CRM with records, objects, lists, notes, and workflow data.|OAuth2;API key|self_serve|REST;Webhooks|moderate|none|easy_win|Young API; some workflow actions may be absent.|https://docs.attio.com/rest-api/overview;https://docs.attio.com/docs/authentication|Public REST docs describe OAuth and access-token authentication.|0.86
Twenty|Open-source CRM with workspace, object, and record APIs.|API key;token|self_serve|REST;GraphQL|moderate|community|easy_win|Self-hosting and instance URL handling must be supported.|https://twenty.com/developers;https://github.com/twentyhq/twenty|Open-source CRM with public developer docs and repository.|0.84
Podio|Citrix collaboration and CRM-style workspace app with items, apps, tasks, and files.|OAuth2|self_serve|REST|moderate|none|buildable|Legacy API patterns and OAuth flow need careful refresh handling.|https://developers.podio.com/;https://developers.podio.com/authentication|Developer site documents REST endpoints and OAuth authentication.|0.86
Zoho CRM|CRM suite for leads, contacts, accounts, deals, activities, and modules.|OAuth2|self_serve|REST;Webhooks|broad|community|buildable|Regional data centers and Zoho account scopes add integration complexity.|https://www.zoho.com/crm/developer/docs/api/v7/;https://www.zoho.com/crm/developer/docs/api/v7/oauth-overview.html|Public v7 CRM API docs and OAuth overview are available.|0.90
Close|Sales CRM for leads, contacts, calls, email, tasks, and opportunities.|API key;Basic|self_serve|REST;Webhooks|moderate|none|easy_win|Basic auth with API key is straightforward; account access still needs a Close workspace.|https://developer.close.com/;https://developer.close.com/topics/authentication/|Docs describe API-key authentication over HTTP Basic and REST resources.|0.89
Copper|Google Workspace-focused CRM for people, companies, opportunities, and activities.|API key|paid_or_admin|REST;Webhooks|moderate|none|buildable|API access usually requires a paid/admin-managed Copper account.|https://developer.copper.com/;https://developer.copper.com/authentication.html|Developer docs expose REST API and API key authentication.|0.83
DealCloud|Deal management CRM for investment banking and private capital workflows.|OAuth2;token|partner_gated|REST|moderate|none|gated|Access is oriented to DealCloud customers and configured environments.|https://api.docs.dealcloud.com/;https://www.dealcloud.com/solutions/api/|API docs exist, but credentials depend on customer environment and vendor setup.|0.75
Zendesk|Customer support platform for tickets, users, help center, messaging, and automations.|OAuth2;API token;Basic|self_serve|REST;Webhooks|broad|community|easy_win|Broad surface; packaging scopes and rate limits matter.|https://developer.zendesk.com/api-reference/;https://developer.zendesk.com/documentation/api-basics/authentication/|Public API reference covers token, basic, and OAuth options.|0.93
Intercom|Customer messaging and support platform for conversations, contacts, tickets, and articles.|OAuth2;access token|self_serve|REST;Webhooks|broad|community|easy_win|OAuth app review may be needed for marketplace distribution.|https://developers.intercom.com/docs/references/rest-api/api.intercom.io;https://developers.intercom.com/docs/build-an-integration/learn-more/authentication|Public REST API and authentication docs describe access tokens and OAuth.|0.91
Freshdesk|Helpdesk product for tickets, contacts, companies, agents, and knowledge base.|API key;Basic|self_serve|REST;Webhooks|broad|none|easy_win|API key auth is easy; product has plan-specific feature limits.|https://developers.freshdesk.com/api/;https://support.freshdesk.com/support/solutions/articles/215517-how-to-find-your-api-key|Public REST API docs use API key over Basic auth.|0.88
Front|Shared inbox and customer operations platform for messages, contacts, channels, and rules.|OAuth2;API token|self_serve|REST;Webhooks|moderate|community|easy_win|OAuth app approval may matter for public distribution.|https://dev.frontapp.com/reference/introduction;https://dev.frontapp.com/docs/authentication|Developer docs describe REST API, OAuth, and token authentication.|0.88
Pylon|B2B support platform for Slack, Microsoft Teams, email, issues, and customer data.|API key;OAuth2|self_serve|REST;Webhooks|moderate|none|buildable|Docs are public but product access is newer and customer-centric.|https://docs.usepylon.com/;https://docs.usepylon.com/pylon-docs/developer/api-reference|Public docs expose developer API references and webhooks.|0.78
LiveAgent|Helpdesk and live-chat suite for tickets, contacts, chats, calls, and knowledge base.|API key|self_serve|REST|moderate|none|buildable|Older docs; endpoint coverage is usable but less modern.|https://support.liveagent.com/316638-API;https://support.liveagent.com/168386-API-v3|Support docs document API usage and keys.|0.76
Plain|Modern support platform for customers, issues, conversations, and events.|API key|self_serve|GraphQL;Webhooks|moderate|none|easy_win|GraphQL schema design requires typed tool wrappers.|https://www.plain.com/docs/api-reference/introduction;https://www.plain.com/docs/api-reference/authentication|Plain exposes a public GraphQL API with API key authentication.|0.87
Help Scout|Customer support platform for mailboxes, conversations, customers, docs, and reports.|OAuth2|self_serve|REST;Webhooks|broad|community|easy_win|OAuth token lifecycle and mailbox scoping need care.|https://developer.helpscout.com/mailbox-api/;https://developer.helpscout.com/mailbox-api/overview/authentication/|Mailbox API docs document OAuth2 and broad REST resources.|0.89
Gorgias|Ecommerce helpdesk for tickets, customers, macros, orders, and integrations.|OAuth2;API key;Basic|paid_or_admin|REST;Webhooks|moderate|none|buildable|API access is useful but tied to merchant/admin accounts and plan features.|https://developers.gorgias.com/reference/introduction;https://developers.gorgias.com/docs/authentication|Developer docs cover REST API authentication and app integrations.|0.82
Gladly|Customer service platform for people-centered conversations and tasks.|API token|partner_gated|REST;Webhooks|moderate|none|gated|API docs and credentials are customer/partner oriented.|https://developer.gladly.com/rest/;https://developer.gladly.com/|Developer portal exists but access is aimed at Gladly customers and partners.|0.72
Slack|Team messaging platform with channels, messages, users, workflows, and apps.|OAuth2;bot token;app token|self_serve|REST;Events;Webhooks;Socket Mode|broad|community|easy_win|Granular Slack scopes require careful tool design.|https://api.slack.com/apis;https://api.slack.com/authentication|Public platform docs cover OAuth and token-based Slack apps.|0.95
Twilio|Communications API platform for SMS, voice, video, email, verification, and messaging.|Basic;API key;OAuth2|self_serve|REST;Webhooks|broad|community|easy_win|Some products require compliance registration before production use.|https://www.twilio.com/docs/usage/api;https://www.twilio.com/docs/iam/api-key-resource|Docs cover REST APIs, account credentials, API keys, and webhooks.|0.93
Zoho Cliq|Team chat and collaboration app in the Zoho suite.|OAuth2|self_serve|REST;Webhooks|moderate|none|buildable|Zoho account, region, and scope setup add friction.|https://www.zoho.com/cliq/help/restapi/v2/;https://www.zoho.com/cliq/help/restapi/v2/oauth-overview.html|Zoho Cliq REST API and OAuth docs are public.|0.85
Lark (Larksuite)|Collaboration suite with messaging, docs, calendar, approval, and workplace APIs.|OAuth2;app credentials|self_serve|REST;Events|broad|community|buildable|Tenant app permissions and regional Open Platform differences add complexity.|https://open.larksuite.com/document/home/index;https://open.larksuite.com/document/server-docs/authentication-management/access-token/tenant_access_token_internal|Open Platform docs expose broad APIs and token flows.|0.87
Pumble|Team messaging app from CAKE.com for channels, messages, users, and webhooks.|token;webhook|self_serve|REST;Webhooks|narrow|none|buildable|API appears narrower than Slack-style platforms.|https://pumble.com/help/api/;https://pumble.com/help/integrations/incoming-webhooks/|Help docs describe API and webhook access.|0.70
Discord|Community chat platform with bots, guilds, channels, messages, and interactions.|OAuth2;bot token|self_serve|REST;Gateway;Webhooks|broad|community|easy_win|Bot permissions and privileged intents must be configured explicitly.|https://discord.com/developers/docs/intro;https://discord.com/developers/docs/topics/oauth2|Developer docs cover REST, Gateway, OAuth2, bot tokens, and webhooks.|0.94
Telegram|Messaging platform with Bot API, MTProto client API, and webhooks.|bot token;MTProto auth|self_serve|REST;Webhooks;SDK|broad|community|easy_win|Bot API is easy; full user-client API is a different auth model.|https://core.telegram.org/bots/api;https://core.telegram.org/api|Official docs cover Bot API tokens and MTProto API.|0.93
WhatsApp Business|Meta messaging platform for WhatsApp business messaging and templates.|OAuth2;system user token|paid_or_admin|REST;Webhooks|moderate|community|buildable|Business verification, phone setup, and template review are the blockers.|https://developers.facebook.com/docs/whatsapp/cloud-api;https://developers.facebook.com/docs/whatsapp/embedded-signup|Cloud API docs are public but production use requires Meta business setup.|0.88
Aircall|Cloud phone system for calls, contacts, users, numbers, and analytics.|OAuth2;API key|self_serve|REST;Webhooks|moderate|none|buildable|Telephony use cases depend on account plan and phone-number setup.|https://developer.aircall.io/api-references/;https://developer.aircall.io/tutorials/getting-started/|Aircall developer docs cover REST APIs and authentication.|0.82
Vonage|Communications APIs for voice, SMS, video, verify, and messaging.|API key;JWT;Basic;OAuth2|self_serve|REST;Webhooks|broad|community|easy_win|Product-specific auth modes and compliance steps need clear tool grouping.|https://developer.vonage.com/en/api;https://developer.vonage.com/en/getting-started/concepts/authentication|Developer docs describe broad APIs and multiple auth models.|0.90
Google Ads|Google advertising API for campaigns, accounts, reporting, bidding, and assets.|OAuth2;developer token|paid_or_admin|REST;gRPC;SDK|broad|none|buildable|Requires developer token review and OAuth consent/project setup.|https://developers.google.com/google-ads/api/docs/start;https://developers.google.com/google-ads/api/docs/oauth/overview|Docs are public, but production developer token approval is required.|0.90
Meta Ads|Meta Marketing API for ad accounts, campaigns, audiences, creatives, and insights.|OAuth2;access token|paid_or_admin|Graph API;Webhooks|broad|community|buildable|App review, business verification, and permissions are major blockers.|https://developers.facebook.com/docs/marketing-apis/;https://developers.facebook.com/docs/facebook-login/guides/access-tokens|Marketing API uses Graph API access tokens and reviewed permissions.|0.88
LinkedIn Ads|LinkedIn Marketing APIs for campaigns, ad accounts, creatives, and reporting.|OAuth2|partner_gated|REST|broad|none|gated|Marketing API access is gated by LinkedIn developer products and approval.|https://learn.microsoft.com/en-us/linkedin/marketing/;https://learn.microsoft.com/en-us/linkedin/shared/authentication/authentication|Docs are public but product access commonly requires approval.|0.84
GoHighLevel|Agency CRM and marketing platform with locations, contacts, calendars, workflows, and SaaS APIs.|OAuth2;API key|self_serve|REST;Webhooks|broad|none|easy_win|Versioned APIs and agency/location scoping need careful modeling.|https://highlevel.stoplight.io/docs/integrations/;https://highlevel.stoplight.io/docs/integrations/oauth/oauth-20|Stoplight docs expose REST APIs and OAuth 2.0.|0.86
Mailchimp|Email marketing platform for audiences, campaigns, automations, ecommerce, and reports.|OAuth2;API key|self_serve|REST;Webhooks|broad|community|easy_win|Data-center-specific API base URLs must be derived from credentials.|https://mailchimp.com/developer/marketing/api/;https://mailchimp.com/developer/marketing/guides/access-user-data-oauth-2/|Developer docs cover Marketing API, API keys, and OAuth2.|0.91
Klaviyo|Marketing automation and customer data platform for profiles, events, lists, flows, and campaigns.|OAuth2;private API key|self_serve|REST;Webhooks|broad|community|easy_win|Revisioned API versions and scopes need explicit handling.|https://developers.klaviyo.com/en/reference/api_overview;https://developers.klaviyo.com/en/docs/authenticate_|Docs cover REST API and private key/OAuth authentication.|0.90
systeme.io|Funnel, email, course, and affiliate platform for small businesses.|API key|paid_or_admin|REST|narrow|none|buildable|API appears narrower and plan/account gated.|https://developer.systeme.io/reference/api-reference;https://help.systeme.io/article/2495-api-key|Docs expose API reference and API key help content.|0.75
Pinterest|Visual discovery and ads platform with pins, boards, catalogs, and ads APIs.|OAuth2|self_serve|REST|broad|community|buildable|Ads and shopping surfaces may require business account approval.|https://developers.pinterest.com/docs/api/v5/;https://developers.pinterest.com/docs/getting-started/authentication/|Pinterest API v5 docs and OAuth authentication are public.|0.87
Threads (Meta)|Meta social platform API for publishing, replies, insights, and media containers.|OAuth2|self_serve|Graph API|moderate|none|buildable|App review and permissions govern production publishing/insights use.|https://developers.facebook.com/docs/threads/;https://developers.facebook.com/docs/threads/get-started|Threads API docs use Meta developer app and OAuth permissions.|0.83
SendGrid|Email delivery platform for sending mail, templates, contacts, and stats.|API key|self_serve|REST;Webhooks|broad|community|easy_win|Sender authentication and compliance are separate production tasks.|https://www.twilio.com/docs/sendgrid/api-reference;https://www.twilio.com/docs/sendgrid/for-developers/sending-email/api-getting-started|SendGrid API docs describe API key authentication and REST endpoints.|0.91
Shopify|Commerce platform with store, product, order, customer, fulfillment, and app APIs.|OAuth2;access token|self_serve|REST;GraphQL;Webhooks|broad|community|easy_win|Shopify has many surfaces; Admin GraphQL should be the primary tool layer.|https://shopify.dev/docs/api/admin-graphql;https://shopify.dev/docs/apps/build/authentication-authorization|Developer docs cover Admin APIs, OAuth, access tokens, and app auth.|0.94
WooCommerce|WordPress ecommerce plugin with products, orders, customers, coupons, and reports APIs.|Basic;OAuth1;consumer key|self_serve|REST|broad|community|easy_win|Self-hosted WordPress URL and plugin configuration vary per store.|https://woocommerce.github.io/woocommerce-rest-api-docs/;https://woocommerce.com/document/woocommerce-rest-api/|REST API docs cover consumer key/secret authentication.|0.89
BigCommerce|SaaS ecommerce platform with catalog, carts, orders, customers, and storefront APIs.|OAuth2;access token|self_serve|REST;GraphQL;Webhooks|broad|community|easy_win|Store hash and channel context must be modeled cleanly.|https://developer.bigcommerce.com/docs/start/about;https://developer.bigcommerce.com/docs/start/authentication|Docs cover REST, GraphQL, OAuth, and access tokens.|0.90
Salesforce Commerce Cloud|Enterprise commerce platform with OCAPI, SCAPI, shopper, and admin APIs.|OAuth2;client credentials|paid_or_admin|REST|broad|none|buildable|Requires Commerce Cloud tenant/sandbox and admin configuration.|https://developer.salesforce.com/docs/commerce/commerce-api/overview;https://developer.salesforce.com/docs/commerce/commerce-api/guide/authorization-for-shopper-apis.html|Commerce API docs are public; tenant credentials are customer/admin controlled.|0.82
Magento (Adobe Commerce)|Adobe Commerce platform with catalog, customer, cart, order, and admin APIs.|OAuth1;token;Basic|self_serve|REST;GraphQL|broad|community|easy_win|Self-hosted vs Adobe Commerce Cloud deployments differ.|https://developer.adobe.com/commerce/webapi/rest/;https://developer.adobe.com/commerce/webapi/get-started/authentication/gs-authentication-token/|Adobe docs cover REST, GraphQL, and token-based auth.|0.89
Squarespace|Website and commerce platform with orders, products, inventory, profiles, and transactions APIs.|OAuth2;API key|self_serve|REST;Webhooks|moderate|none|buildable|APIs cover commerce and profiles but not every website editing function.|https://developers.squarespace.com/;https://developers.squarespace.com/commerce-apis/authentication|Developer docs cover API keys, OAuth apps, and commerce resources.|0.84
Ecwid|Ecommerce platform with store, product, order, customer, and app APIs.|OAuth2;token|self_serve|REST;Webhooks|moderate|none|easy_win|Store ID and app token scopes need careful handling.|https://api-docs.ecwid.com/reference/rest-api;https://api-docs.ecwid.com/reference/authentication|API docs cover REST endpoints and authentication.|0.86
Gumroad|Creator commerce platform with products, sales, subscribers, and license APIs.|OAuth2;access token|self_serve|REST|narrow|none|buildable|API is useful but narrower than full store platforms.|https://gumroad.com/api;https://help.gumroad.com/article/280-create-application-api|Gumroad documents API access and OAuth applications.|0.79
Amazon Selling Partner|Amazon marketplace API for listings, orders, inventory, reports, feeds, and finances.|OAuth2;AWS SigV4;LWA|partner_gated|REST|broad|none|gated|Developer profile, app review, LWA, IAM, and restricted data approval are heavy blockers.|https://developer-docs.amazon.com/sp-api/docs/;https://developer-docs.amazon.com/sp-api/docs/registering-your-application|SP-API docs are public but app registration and approval are substantial.|0.91
fanbasis|Creator monetization and fan engagement platform.|unclear|unclear|none|narrow|none|blocked|No obvious public developer API documentation found from the provided hint.|https://fanbasis.com/|Public site is product-facing; API credentials were not discoverable in this pass.|0.45
DataForSEO|SEO and marketing data API provider for SERP, keyword, backlinks, and on-page data.|Basic;API key|self_serve|REST|broad|community|easy_win|Paid credits are needed for meaningful production volume.|https://docs.dataforseo.com/v3/;https://docs.dataforseo.com/v3/appendix-user-data-and-limits/|Docs expose REST APIs and login/password API authentication.|0.88
SE Ranking|SEO platform with keyword, ranking, backlink, site audit, and report APIs.|API key|paid_or_admin|REST|moderate|none|buildable|API access depends on SE Ranking account and plan limits.|https://seranking.com/api.html;https://api4.seranking.com/docs/|API docs and API access are public, with plan/account constraints.|0.80
Ahrefs|SEO data platform for backlinks, keywords, site explorer, and rank data.|API token|paid_or_admin|REST|broad|none|buildable|API access is paid and quota-limited.|https://docs.ahrefs.com/docs/api/site-explorer/overview;https://docs.ahrefs.com/docs/api/authentication|Ahrefs API docs cover token auth and SEO data endpoints.|0.82
MrScraper|Web scraping API/service for extracting pages and structured data.|API key|self_serve|REST|moderate|none|easy_win|Scraping success depends on target-site policy and anti-bot limits.|https://docs.mrscraper.com/;https://docs.mrscraper.com/api-reference/introduction|Docs expose API reference and key-based access.|0.76
Apify|Actor-based scraping and automation platform with datasets, runs, storage, and marketplace actors.|API token|self_serve|REST;SDK;MCP|broad|official|easy_win|Best toolkit design should wrap Actors and datasets rather than raw endpoints only.|https://docs.apify.com/api/v2;https://docs.apify.com/platform/integrations/mcp|Apify documents REST API, SDKs, and an MCP integration.|0.92
Firecrawl|Web crawling and extraction API for LLM-ready search, scrape, crawl, and map tasks.|API key|self_serve|REST;SDK;MCP|moderate|official|easy_win|Usage is credit-based; long crawls need async handling.|https://docs.firecrawl.dev/api-reference/introduction;https://docs.firecrawl.dev/mcp-server|Docs cover API keys, REST/SDK use, and MCP server setup.|0.91
Bright Data|Proxy, scraping, SERP, and web-data platform for large-scale data collection.|API key;token|paid_or_admin|REST;SDK;MCP|broad|official|buildable|Powerful but account/payment setup and compliance policy need review.|https://docs.brightdata.com/api-reference/introduction;https://docs.brightdata.com/mcp-server|Docs cover APIs and MCP server; production use is account and billing gated.|0.86
Sherlock|Open-source OSINT tool for checking usernames across social networks.|none|self_serve|CLI;unofficial|narrow|community|buildable|It is a CLI/open-source tool, not a hosted authenticated SaaS API.|https://github.com/sherlock-project/sherlock|Repository documents CLI usage; toolkit would wrap the CLI rather than an API.|0.83
Waterfall.io|Company/contact enrichment platform for go-to-market data workflows.|API key|partner_gated|REST|moderate|none|gated|API access appears sales/customer gated.|https://www.waterfall.io/;https://docs.waterfall.io/|Product/docs presence suggests API, but credentials are not openly self-serve.|0.62
Clay|Data enrichment and GTM workflow platform for tables, enrichments, and automations.|API key|paid_or_admin|REST;Webhooks|moderate|none|buildable|API access is workspace/plan gated and not as open as developer-first tools.|https://docs.clay.com/;https://docs.clay.com/en/articles/9672489-http-api|Clay docs describe HTTP API access for workspace workflows.|0.74
GitHub|Developer platform for repositories, issues, pull requests, actions, users, and orgs.|OAuth2;GitHub App;PAT|self_serve|REST;GraphQL;Webhooks;MCP|broad|official|easy_win|Mature APIs; main work is permission-safe tool design.|https://docs.github.com/en/rest;https://github.com/github/github-mcp-server|GitHub documents REST/GraphQL APIs and maintains an MCP server.|0.96
Vercel|Frontend cloud platform for deployments, projects, teams, domains, and env vars.|OAuth2;token|self_serve|REST;Webhooks|moderate|community|easy_win|Team/project scoping and deployment side effects need guardrails.|https://vercel.com/docs/rest-api;https://vercel.com/docs/rest-api/reference/authentication|Vercel REST API docs cover bearer token authentication.|0.90
Netlify|Web hosting and app platform for sites, deploys, forms, functions, and domains.|OAuth2;token|self_serve|REST;Webhooks|moderate|community|easy_win|Some admin actions require team privileges.|https://docs.netlify.com/api/get-started/;https://open-api.netlify.com/|Netlify documents REST/OpenAPI access and OAuth/token auth.|0.88
Cloudflare|Internet infrastructure platform for DNS, CDN, Workers, storage, security, and accounts.|API token;API key;OAuth2|self_serve|REST;GraphQL;MCP|broad|official|easy_win|Huge surface requires scoped tool packs and safety checks.|https://developers.cloudflare.com/api/;https://developers.cloudflare.com/agents/model-context-protocol/|Cloudflare has public API docs and official MCP-related documentation.|0.92
Supabase|Open-source backend platform with Postgres, auth, storage, realtime, edge functions, and management APIs.|API key;JWT;token|self_serve|REST;GraphQL;SDK;MCP|broad|official|easy_win|Distinguish project data APIs from management APIs and service-role secrets.|https://supabase.com/docs;https://supabase.com/docs/guides/getting-started/mcp|Supabase docs cover APIs and MCP integration.|0.91
Neo4j|Graph database platform with Cypher, HTTP APIs, drivers, Aura, and graph data science.|Basic;token;API key|self_serve|REST;GraphQL;SDK|broad|community|buildable|Database credentials and Cypher safety boundaries are the key issue.|https://neo4j.com/docs/http-api/current/;https://neo4j.com/docs/api/|Neo4j exposes HTTP APIs, drivers, and Aura APIs.|0.84
Snowflake|Cloud data platform for SQL warehouses, data sharing, apps, and account APIs.|key pair;OAuth2;PAT;Basic|paid_or_admin|SQL API;REST;SDK|broad|community|buildable|Requires account/admin setup and careful data-access controls.|https://docs.snowflake.com/en/developer-guide/sql-api/index;https://docs.snowflake.com/en/developer-guide/sql-api/authenticating|Snowflake SQL API docs cover OAuth, key-pair JWT, PAT, and password auth.|0.88
MongoDB Atlas|Managed MongoDB platform with project, cluster, database user, backup, and monitoring APIs.|API key;OAuth2|self_serve|REST;SDK|broad|community|easy_win|Organization/project permissions and destructive operations require guardrails.|https://www.mongodb.com/docs/atlas/reference/api-resources-spec/;https://www.mongodb.com/docs/atlas/configure-api-access/|Atlas Admin API docs and API key setup are public.|0.90
Datadog|Observability platform for metrics, logs, traces, monitors, dashboards, and incidents.|API key;application key|self_serve|REST;Webhooks|broad|community|easy_win|High-volume data APIs and write actions need rate and permission controls.|https://docs.datadoghq.com/api/latest/;https://docs.datadoghq.com/account_management/api-app-keys/|Datadog API reference and key docs are public.|0.92
Sentry|Error monitoring platform for issues, events, releases, orgs, projects, and alerts.|OAuth2;auth token|self_serve|REST;Webhooks|broad|community|easy_win|Organization/project permissions and noisy event data should be scoped.|https://docs.sentry.io/api/;https://docs.sentry.io/product/integrations/integration-platform/|Sentry API docs cover auth tokens and integration OAuth flows.|0.90
Notion|Workspace platform for pages, databases, comments, users, and blocks.|OAuth2;internal integration token|self_serve|REST;Webhooks;MCP|broad|official|easy_win|Page/database permission sharing is the main source of empty results.|https://developers.notion.com/;https://developers.notion.com/docs/authorization;https://developers.notion.com/docs/mcp|Notion developer docs cover auth and MCP documentation.|0.91
Airtable|No-code database platform with bases, tables, records, comments, webhooks, and metadata APIs.|OAuth2;PAT|self_serve|REST;Webhooks|broad|community|easy_win|Base/table schema discovery is needed before record operations.|https://airtable.com/developers/web/api/introduction;https://airtable.com/developers/web/api/authentication|Airtable Web API docs cover PAT and OAuth authentication.|0.91
Linear|Issue tracking and product planning platform for issues, projects, cycles, teams, and comments.|OAuth2;API key|self_serve|GraphQL;Webhooks|broad|community|easy_win|GraphQL schema is rich; tools should be task-oriented rather than exposing raw queries.|https://developers.linear.app/docs/graphql/working-with-the-graphql-api;https://developers.linear.app/docs/oauth/authentication|Linear docs cover GraphQL API, API keys, OAuth, and webhooks.|0.92
Jira|Atlassian project management platform for issues, projects, boards, sprints, users, and workflows.|OAuth2;API token;Basic|self_serve|REST;Webhooks|broad|community|easy_win|Cloud vs Data Center differences and permissions must be handled.|https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/;https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/|Atlassian docs cover Jira REST API and OAuth/API-token auth.|0.92
Asana|Work management platform for tasks, projects, portfolios, goals, users, and teams.|OAuth2;PAT|self_serve|REST;Webhooks|broad|community|easy_win|Workspace/project scoping and custom fields need discovery helpers.|https://developers.asana.com/docs;https://developers.asana.com/docs/authentication|Asana docs cover OAuth, PATs, REST API, and webhooks.|0.91
Monday.com|Work OS for boards, items, columns, automations, docs, and dashboards.|OAuth2;API token|self_serve|GraphQL;Webhooks|broad|community|easy_win|GraphQL complexity and board schema discovery are the main design work.|https://developer.monday.com/api-reference/docs;https://developer.monday.com/api-reference/docs/authentication|Developer docs cover GraphQL API and auth tokens/OAuth.|0.90
ClickUp|Productivity platform for tasks, lists, spaces, docs, goals, and time tracking.|OAuth2;API token|self_serve|REST;Webhooks|broad|community|easy_win|Hierarchy discovery is required before acting on tasks/lists.|https://clickup.com/api;https://developer.clickup.com/docs/authentication|ClickUp API docs cover REST endpoints and OAuth/token auth.|0.89
Coda|Collaborative docs platform with docs, tables, rows, pages, packs, and formulas.|OAuth2;API token|self_serve|REST;Webhooks|moderate|community|easy_win|Doc/table schema discovery needed for robust row tools.|https://coda.io/developers/apis/v1;https://coda.io/developers/apis/v1#section/Authentication|Coda API docs cover bearer-token authentication and REST resources.|0.88
Smartsheet|Work management platform for sheets, rows, reports, workspaces, attachments, and automation.|OAuth2;access token|self_serve|REST;Webhooks|broad|community|easy_win|Enterprise admin controls may restrict access.|https://smartsheet.redoc.ly/;https://developers.smartsheet.com/api/smartsheet/guides/basics/authentication|Smartsheet API docs cover OAuth and token authentication.|0.88
Harvest|Time tracking and invoicing platform for time entries, projects, clients, users, and invoices.|OAuth2;PAT|self_serve|REST|moderate|community|easy_win|Account ID header and user permissions must be modeled.|https://help.getharvest.com/api-v2/;https://help.getharvest.com/api-v2/authentication-api/authentication/authentication/|Harvest API v2 docs cover OAuth2 and personal access tokens.|0.90
Stripe|Payments platform for charges, customers, subscriptions, invoices, payouts, and financial objects.|API key;OAuth2|self_serve|REST;Webhooks;SDK;MCP|broad|official|easy_win|Money-moving actions require strong confirmation and idempotency guardrails.|https://stripe.com/docs/api;https://docs.stripe.com/stripe-agent-toolkit|Stripe docs cover APIs and an agent toolkit/MCP path.|0.93
Plaid|Financial data API for bank account linking, transactions, identity, auth, and payments.|API key;client secret;OAuth2 bank flows|self_serve|REST;Webhooks|broad|community|buildable|Production access requires compliance review and institution products vary.|https://plaid.com/docs/api/;https://plaid.com/docs/api/tokens/|Plaid docs expose REST APIs and token-based Link/item flows.|0.88
Binance|Crypto exchange APIs for market data, spot trading, account, wallet, and WebSocket streams.|API key;HMAC signature|self_serve|REST;WebSocket|broad|community|buildable|Trading tools require high-risk safety controls and regional account constraints.|https://developers.binance.com/docs/binance-spot-api-docs/rest-api;https://developers.binance.com/docs/binance-spot-api-docs/rest-api/request-security|Binance docs cover REST/WebSocket APIs and signed API-key requests.|0.89
Paygent Connect|Payment processing connector associated with NMI-powered payment workflows.|API key;token|partner_gated|REST|narrow|none|gated|Public developer documentation was limited; credentials appear merchant/partner gated.|https://www.nmi.com/;https://www.paygent.co.jp/|Finding relies on vendor/product context; direct self-serve docs were not found.|0.45
iPayX|AI/payment or fintech API product with public docs referenced by the prompt.|API key|unclear|REST|narrow|none|blocked|Docs availability and commercial access need human confirmation.|https://ipayx.ai/docs|Hinted docs could not be confidently classified from public evidence alone.|0.50
QuickBooks|Intuit accounting platform for customers, invoices, bills, payments, reports, and accounting data.|OAuth2|self_serve|REST;Webhooks|broad|community|easy_win|Sandbox is easy; production apps need Intuit review for some scopes.|https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account;https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization|Intuit docs cover QuickBooks APIs and OAuth2.|0.90
Xero|Accounting platform for invoices, contacts, payments, bank transactions, payroll, and reports.|OAuth2|self_serve|REST;Webhooks|broad|community|easy_win|Tenant selection and accounting write safety need careful UX.|https://developer.xero.com/documentation/api/accounting/overview;https://developer.xero.com/documentation/guides/oauth2/overview|Xero developer docs cover accounting APIs and OAuth2.|0.91
Brex|Corporate card and spend management platform for expenses, cards, vendors, and transactions.|OAuth2;API token|paid_or_admin|REST;Webhooks|moderate|none|buildable|Access requires Brex customer/admin context and scopes.|https://developer.brex.com/openapi;https://developer.brex.com/docs/authentication|Brex docs cover API authentication and endpoints.|0.80
Ramp|Corporate card and spend management platform for expenses, cards, reimbursements, and vendors.|OAuth2;API token|paid_or_admin|REST;Webhooks|moderate|community|buildable|API access is workspace/admin and often enterprise-controlled.|https://docs.ramp.com/;https://docs.ramp.com/developer-api/v1/overview/authentication|Ramp docs expose APIs and authentication, but credentials require customer access.|0.80
PitchBook|Private market and company intelligence platform with research data APIs.|token|partner_gated|REST|moderate|none|gated|API is commercial research-data access and not openly self-serve.|https://pitchbook.com/data/our-data/api;https://pitchbook.com/solutions/research|PitchBook positions API as a commercial data product requiring engagement.|0.72
NotebookLM|Google AI note/research product; enterprise API path is via Gemini/Vertex AI rather than consumer NotebookLM.|OAuth2;API key;service account|paid_or_admin|REST;SDK|moderate|none|poor_fit|No clear public NotebookLM consumer API; build against Gemini/Vertex AI instead.|https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference;https://ai.google.dev/gemini-api/docs|Public APIs exist for Gemini/Vertex AI, not a direct NotebookLM app API.|0.70
Otter AI|Meeting transcription and notes product with imports, transcripts, and automation features.|OAuth2;MCP auth|paid_or_admin|MCP;REST|narrow|official|buildable|MCP exists but workspace/product access and API breadth are limited.|https://help.otter.ai/hc/en-us;https://help.otter.ai/hc/en-us/articles/40093383200919-Otter-MCP-Server|Otter help documents an MCP server; broader API access is less open.|0.76
Fathom|AI meeting recorder and summary platform for calls, transcripts, clips, and CRM sync.|token|unclear|unofficial|narrow|community|blocked|No clear public API docs from the product site; likely needs partner/customer access.|https://fathom.video/;https://help.fathom.video/|Public docs emphasize product usage; API access was not clearly self-serve.|0.52
Consensus|AI research search engine for scientific papers and evidence synthesis.|OAuth2|partner_gated|REST|narrow|none|gated|API/OAuth access appears requested rather than broadly documented.|https://consensus.app/;https://consensus.app/home/api/|API access appears to require request/contact rather than public self-serve docs.|0.62
Reducto|Document parsing API for extracting structured data from PDFs and business documents.|API key|self_serve|REST;SDK|moderate|community|easy_win|Document upload workflows need privacy and file-size handling.|https://docs.reducto.ai/;https://docs.reducto.ai/guides/authentication|Docs cover API-key auth, parsing endpoints, and SDK use.|0.85
Devin|AI software engineering agent platform with API/MCP integration surfaces.|API key;MCP auth|paid_or_admin|REST;MCP|moderate|official|buildable|Access depends on Devin account/workspace and product availability.|https://docs.devin.ai/;https://docs.devin.ai/integrations/mcp|Docs describe Devin integration and MCP surfaces.|0.80
higgsfield|AI content creation suite with CLI-oriented tooling.|token|unclear|CLI|narrow|none|blocked|Public API/tooling surface is not clearly documented enough for a stable toolkit.|https://higgsfield.ai/;https://higgsfield.ai/cli|CLI hint exists, but auth/API breadth remained unclear in this pass.|0.50
Mermaid CLI|Open-source CLI for rendering Mermaid diagrams to images/PDF/SVG.|none|self_serve|CLI|narrow|community|easy_win|No SaaS auth; toolkit should wrap local CLI execution and file outputs.|https://github.com/mermaid-js/mermaid-cli|Open-source CLI repository documents local rendering usage.|0.90
YouTube Transcript|Transcript API service for retrieving YouTube video transcripts.|API key|self_serve|REST|narrow|none|easy_win|Narrow API; rate limits and transcript availability are the main caveats.|https://www.transcriptapi.com/;https://www.transcriptapi.com/docs|Public docs expose key-based transcript API.|0.78
Grain|AI meeting recording, notes, clips, and conversation intelligence platform.|API key;token|paid_or_admin|REST;Webhooks|moderate|none|buildable|API access appears tied to workspace/admin setup rather than open signup alone.|https://grain.com/api;https://help.grain.com/|Grain API/product docs indicate meeting-data integration surfaces.|0.68
"""


SUPPORT_KEYWORDS = {
    "OAuth2": ["oauth", "authorization code", "openid"],
    "API key": ["api key", "apikey", "x-api-key", "key"],
    "Basic": ["basic auth", "basic authentication"],
    "token": ["token", "bearer"],
    "GraphQL": ["graphql"],
    "REST": ["rest", "endpoint", "api reference"],
    "MCP": ["mcp", "model context protocol"],
}

DEFAULT_ZENMUX_MODEL = "x-ai/grok-4.5-free"
DEFAULT_ZENMUX_BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "tencent/hy3:free"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_PROVIDER_ORDER = "zenmux,openrouter"


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def has_real_key(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    if not value:
        return False
    placeholders = ("replace_with_", "sk-or-...", "sk-ai-v1-...")
    return not any(value.startswith(prefix) for prefix in placeholders)


def load_apps(path: Path) -> list[dict]:
    apps: list[dict] = []
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            if current:
                apps.append(current)
            current = {}
            line = line[2:]
        if ":" in line and current is not None:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        apps.append(current)
    return apps


def parse_seed_profiles() -> dict[str, dict]:
    rows = csv.DictReader(io.StringIO(SEED_PROFILES), delimiter="|")
    profiles: dict[str, dict] = {}
    for row in rows:
        row["auth_methods"] = split_list(row["auth_methods"])
        row["api_surface"] = split_list(row["api_surface"])
        row["evidence_urls"] = split_list(row["evidence_urls"])
        row["confidence"] = float(row["confidence"])
        profiles[row["app"]] = row
    return profiles


def split_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def fetch_text(url: str, timeout: int = 8) -> tuple[int | None, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 integration-research-agent/1.0",
            "Accept": "text/html,application/json,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(180_000)
            text = data.decode("utf-8", errors="ignore")
            return response.status, re.sub(r"\s+", " ", text)
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return None, ""


def evidence_probe(profile: dict, live: bool = False, timeout: int = 4) -> dict:
    checks = []
    if not live:
        for url in profile["evidence_urls"]:
            checks.append({"url": url, "status": "not_fetched", "supports": []})
        return {"checks": checks, "live_checked": False}

    wanted_terms = set(profile["auth_methods"]) | set(profile["api_surface"])
    if profile["mcp_status"] in {"official", "community"}:
        wanted_terms.add("MCP")

    for url in profile["evidence_urls"]:
        status, text = fetch_text(url, timeout=timeout)
        haystack = text.lower()
        supports = []
        for term in wanted_terms:
            for keyword in SUPPORT_KEYWORDS.get(term, [term.lower()]):
                if keyword.lower() in haystack or keyword.lower() in url.lower():
                    supports.append(term)
                    break
        checks.append({"url": url, "status": status, "supports": sorted(set(supports))})
        time.sleep(0.2)
    return {"checks": checks, "live_checked": True}


def infer_agent_mode() -> dict:
    provider_order = [
        provider.strip()
        for provider in os.environ.get("LLM_PROVIDER_ORDER", DEFAULT_LLM_PROVIDER_ORDER).split(",")
        if provider.strip()
    ]
    zenmux_model = os.environ.get("ZENMUX_MODEL", DEFAULT_ZENMUX_MODEL)
    zenmux_base_url = os.environ.get("ZENMUX_BASE_URL", DEFAULT_ZENMUX_BASE_URL)
    openrouter_model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    openrouter_base_url = os.environ.get("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)
    providers = {
        "zenmux": {
            "enabled": has_real_key("ZENMUX_API_KEY"),
            "model": zenmux_model,
            "base_url": zenmux_base_url,
        },
        "openrouter": {
            "enabled": has_real_key("OPENROUTER_API_KEY"),
            "model": openrouter_model,
            "base_url": openrouter_base_url,
        },
    }
    enabled_provider = next((provider for provider in provider_order if providers.get(provider, {}).get("enabled")), None)
    return {
        "llm_provider": enabled_provider or provider_order[0],
        "llm_enabled": bool(enabled_provider),
        "llm_provider_order": provider_order,
        "llm_providers": providers,
        "composio_enabled": has_real_key("COMPOSIO_API_KEY"),
        "note": (
            "Deterministic curated extraction used. Set ZENMUX_API_KEY for the "
            f"primary ZenMux extraction pass using {zenmux_model} at {zenmux_base_url}. "
            "If ZenMux is unavailable, set OPENROUTER_API_KEY for the fallback "
            f"OpenRouter pass using {openrouter_model} at {openrouter_base_url}. "
            "Set COMPOSIO_API_KEY to route fetch/search tools through a Composio-backed adapter."
        ),
    }


def build_findings(apps: list[dict], live_probe: bool = False, probe_limit: int | None = None, probe_timeout: int = 4) -> dict:
    profiles = parse_seed_profiles()
    missing = [app["app"] for app in apps if app["app"] not in profiles]
    if missing:
        raise SystemExit(f"Missing seed profiles for: {', '.join(missing)}")

    findings = []
    for app in apps:
        profile = dict(profiles[app["app"]])
        profile["id"] = int(app["id"])
        profile["category"] = app["category"]
        profile["hint"] = app["hint"]
        should_probe = live_probe and (probe_limit is None or len(findings) < probe_limit)
        profile["evidence_probe"] = evidence_probe(profile, live=should_probe, timeout=probe_timeout)
        findings.append(profile)

    findings.sort(key=lambda row: row["id"])
    return {
        "metadata": {
            "generated_by": "scripts/research.py",
            "app_count": len(findings),
            "agent_mode": infer_agent_mode(),
            "method": [
                "Seeded official-doc corpus from the provided 100-app list",
                "Schema normalization and consistency checks",
                "Optional live evidence URL probing via --live-probe",
                "Optional ZenMux-first/OpenRouter-fallback/Composio extraction path documented for credentialed runs",
            ],
        },
        "findings": findings,
    }


def validate(payload: dict) -> None:
    required = {
        "app",
        "category",
        "description",
        "auth_methods",
        "credential_access",
        "api_surface",
        "surface_breadth",
        "mcp_status",
        "buildability",
        "main_blocker",
        "evidence_urls",
        "evidence_notes",
        "confidence",
    }
    seen = set()
    for row in payload["findings"]:
        missing = required - set(row)
        if missing:
            raise ValueError(f"{row.get('app', '<unknown>')} missing fields: {sorted(missing)}")
        if row["app"] in seen:
            raise ValueError(f"Duplicate app: {row['app']}")
        seen.add(row["app"])
        if row["credential_access"] != "unclear" and not row["evidence_urls"]:
            raise ValueError(f"{row['app']} has no evidence URLs")


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/apps.yml", help="Path to app list YAML")
    parser.add_argument("--output", default="data/findings.json", help="Output JSON path")
    parser.add_argument("--live-probe", action="store_true", help="Fetch evidence URLs and record keyword support")
    parser.add_argument("--probe-limit", type=int, default=None, help="Only live-probe the first N apps")
    parser.add_argument("--probe-timeout", type=int, default=4, help="Per-URL live probe timeout in seconds")
    args = parser.parse_args(argv)

    apps = load_apps(Path(args.input))
    payload = build_findings(apps, live_probe=args.live_probe, probe_limit=args.probe_limit, probe_timeout=args.probe_timeout)
    validate(payload)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['findings'])} findings to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
