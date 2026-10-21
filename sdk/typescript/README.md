# @membrain/sdk@0.1.0

A TypeScript SDK client for the 127.0.0.1 API.

## Usage

First, install the SDK from npm.

```bash
npm install @membrain/sdk --save
```

Next, try it out.


```ts
import {
  Configuration,
  BankManagementApi,
} from '@membrain/sdk';
import type { ArchiveRelationshipRequest } from '@membrain/sdk';

async function example() {
  console.log("🚀 Testing @membrain/sdk SDK...");
  const api = new BankManagementApi();

  const body = {
    // string
    relationshipId: 38400000-8cf0-11bd-b23e-10b96e4ef00d,
    // ArchivePatch
    archivePatch: ...,
  } satisfies ArchiveRelationshipRequest;

  try {
    const data = await api.archiveRelationship(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```


## Documentation

### API Endpoints

All URIs are relative to *http://127.0.0.1:8000*

| Class | Method | HTTP request | Description
| ----- | ------ | ------------ | -------------
*BankManagementApi* | [**archiveRelationship**](docs/BankManagementApi.md#archiverelationship) | **PATCH** /api/v1/relationships/{relationship_id} | Archive Relationship
*BankManagementApi* | [**listConversations**](docs/BankManagementApi.md#listconversations) | **GET** /api/v1/conversations | List Conversations
*BankManagementApi* | [**listResources**](docs/BankManagementApi.md#listresources) | **GET** /api/v1/resources | List Resources
*BankManagementApi* | [**patchConcept**](docs/BankManagementApi.md#patchconcept) | **PATCH** /api/v1/concepts/{concept_id} | Patch Concept
*BankManagementApi* | [**patchResource**](docs/BankManagementApi.md#patchresource) | **PATCH** /api/v1/resources/{resource_id} | Patch Resource
*CapturesApi* | [**bankCapture**](docs/CapturesApi.md#bankcapture) | **POST** /api/v1/captures/{capture_id}/bank | Bank Capture
*CapturesApi* | [**conversationHistory**](docs/CapturesApi.md#conversationhistory) | **GET** /api/v1/conversations/{conversation_id} | Conversation History
*CapturesApi* | [**createCapture**](docs/CapturesApi.md#createcapture) | **POST** /api/v1/captures | Create Capture
*CapturesApi* | [**formatCapture**](docs/CapturesApi.md#formatcapture) | **POST** /api/v1/captures/{capture_id}/format | Format Capture
*CapturesApi* | [**getCapture**](docs/CapturesApi.md#getcapture) | **GET** /api/v1/captures/{capture_id} | Get Capture
*CapturesApi* | [**ingestCapture**](docs/CapturesApi.md#ingestcapture) | **POST** /api/v1/captures/ingest | Ingest Capture
*CapturesApi* | [**listCaptures**](docs/CapturesApi.md#listcaptures) | **GET** /api/v1/captures | List Captures
*CapturesApi* | [**listProposals**](docs/CapturesApi.md#listproposals) | **GET** /api/v1/captures/{capture_id}/proposals | List Proposals
*CapturesApi* | [**rejectProposal**](docs/CapturesApi.md#rejectproposal) | **POST** /api/v1/proposals/{proposal_id}/reject | Reject Proposal
*CapturesApi* | [**undoCapture**](docs/CapturesApi.md#undocapture) | **POST** /api/v1/captures/{capture_id}/undo | Undo Capture
*ConceptMapApi* | [**conceptMap**](docs/ConceptMapApi.md#conceptmap) | **POST** /api/v1/concept-map | Concept Map
*ConversationApi* | [**getTurn**](docs/ConversationApi.md#getturn) | **GET** /api/v1/turns/{turn_id} | Get Turn
*ConversationApi* | [**listTurns**](docs/ConversationApi.md#listturns) | **GET** /api/v1/conversations/{conversation_id}/turns | List Turns
*ConversationApi* | [**retryTurn**](docs/ConversationApi.md#retryturn) | **POST** /api/v1/turns/{turn_id}/retry | Retry Turn
*ConversationApi* | [**submitTurn**](docs/ConversationApi.md#submitturn) | **POST** /api/v1/turns | Submit Turn
*DiscoveryApi* | [**recents**](docs/DiscoveryApi.md#recents) | **GET** /api/v1/recents | Recents
*DiscoveryApi* | [**related**](docs/DiscoveryApi.md#related) | **GET** /api/v1/concepts/{concept_id}/related | Related
*DiscoveryApi* | [**search**](docs/DiscoveryApi.md#search) | **GET** /api/v1/search | Search
*DiscoveryApi* | [**timeline**](docs/DiscoveryApi.md#timeline) | **GET** /api/v1/timeline | Timeline
*HealthApi* | [**health**](docs/HealthApi.md#health) | **GET** /health | Health
*JobsApi* | [**getJob**](docs/JobsApi.md#getjob) | **GET** /api/v1/jobs/{job_id} | Get Job
*JobsApi* | [**retryJob**](docs/JobsApi.md#retryjob) | **POST** /api/v1/jobs/{job_id}/retry | Retry Job
*KnowledgeApi* | [**addRelationship**](docs/KnowledgeApi.md#addrelationship) | **POST** /api/v1/concepts/{concept_id}/relationships | Add Relationship
*KnowledgeApi* | [**addRevision**](docs/KnowledgeApi.md#addrevision) | **POST** /api/v1/concepts/{concept_id}/revisions | Add Revision
*KnowledgeApi* | [**attachResource**](docs/KnowledgeApi.md#attachresource) | **POST** /api/v1/concepts/{concept_id}/resources | Attach Resource
*KnowledgeApi* | [**createResource**](docs/KnowledgeApi.md#createresource) | **POST** /api/v1/resources | Create Resource
*KnowledgeApi* | [**detachResource**](docs/KnowledgeApi.md#detachresource) | **DELETE** /api/v1/concepts/{concept_id}/resources/{resource_id} | Detach Resource
*KnowledgeApi* | [**getConcept**](docs/KnowledgeApi.md#getconcept) | **GET** /api/v1/concepts/{concept_id} | Get Concept
*KnowledgeApi* | [**getResource**](docs/KnowledgeApi.md#getresource) | **GET** /api/v1/resources/{resource_id} | Get Resource
*KnowledgeApi* | [**listConcepts**](docs/KnowledgeApi.md#listconcepts) | **GET** /api/v1/concepts | List Concepts
*KnowledgeApi* | [**listRelationships**](docs/KnowledgeApi.md#listrelationships) | **GET** /api/v1/concepts/{concept_id}/relationships | List Relationships
*KnowledgeApi* | [**listRevisions**](docs/KnowledgeApi.md#listrevisions) | **GET** /api/v1/concepts/{concept_id}/revisions | List Revisions
*KnowledgeApi* | [**queueEmbedding**](docs/KnowledgeApi.md#queueembedding) | **POST** /api/v1/concepts/{concept_id}/embedding | Queue Embedding
*LearningApi* | [**artifactDetail**](docs/LearningApi.md#artifactdetail) | **GET** /api/v1/learning-artifacts/{artifact_id} | Artifact Detail
*LearningApi* | [**createTask**](docs/LearningApi.md#createtask) | **POST** /api/v1/learning-tasks | Create Task
*LearningApi* | [**decideSuggestion**](docs/LearningApi.md#decidesuggestion) | **POST** /api/v1/learning-suggestions/{suggestion_id}/decision | Decide Suggestion
*PermanentDeletionApi* | [**deleteCapture**](docs/PermanentDeletionApi.md#deletecapture) | **DELETE** /api/v1/captures/{capture_id} | Delete Capture
*PermanentDeletionApi* | [**deleteConcept**](docs/PermanentDeletionApi.md#deleteconcept) | **DELETE** /api/v1/concepts/{concept_id} | Delete Concept
*PermanentDeletionApi* | [**deleteResource**](docs/PermanentDeletionApi.md#deleteresource) | **DELETE** /api/v1/resources/{resource_id} | Delete Resource
*PortabilityApi* | [**_export**](docs/PortabilityApi.md#_export) | **GET** /api/v1/bank/export | Export
*PortabilityApi* | [**importData**](docs/PortabilityApi.md#importdata) | **POST** /api/v1/bank/import | Import Data
*ReviewApi* | [**createSession**](docs/ReviewApi.md#createsession) | **POST** /api/v1/review-sessions | Create Session
*ReviewApi* | [**finishSession**](docs/ReviewApi.md#finishsession) | **POST** /api/v1/review-sessions/{session_id}/finish | Finish Session
*ReviewApi* | [**getAttempt**](docs/ReviewApi.md#getattempt) | **GET** /api/v1/review-attempts/{attempt_id} | Get Attempt
*ReviewApi* | [**nextQuestion**](docs/ReviewApi.md#nextquestion) | **POST** /api/v1/review-sessions/{session_id}/next | Next Question
*ReviewApi* | [**recordAttempt**](docs/ReviewApi.md#recordattempt) | **POST** /api/v1/review-sessions/{session_id}/attempts | Record Attempt
*SetupApi* | [**decideMigration**](docs/SetupApi.md#decidemigration) | **POST** /api/v1/embedding-migrations/{migration_id}/{action} | Decide Migration
*SetupApi* | [**getMigration**](docs/SetupApi.md#getmigration) | **GET** /api/v1/embedding-migrations/{migration_id} | Get Migration
*SetupApi* | [**readiness**](docs/SetupApi.md#readiness) | **GET** /health/ready | Readiness
*SetupApi* | [**saveSetup**](docs/SetupApi.md#savesetup) | **PUT** /api/v1/setup | Save Setup
*SetupApi* | [**setupStatus**](docs/SetupApi.md#setupstatus) | **GET** /api/v1/setup | Setup Status
*SetupApi* | [**startMigration**](docs/SetupApi.md#startmigration) | **POST** /api/v1/embedding-migrations | Start Migration
*SetupApi* | [**validateSetup**](docs/SetupApi.md#validatesetup) | **POST** /api/v1/setup/validate | Validate Setup
*SourceContentApi* | [**sourceChunks**](docs/SourceContentApi.md#sourcechunks) | **GET** /api/v1/resources/{resource_id}/chunks | Source Chunks
*SourceContentApi* | [**uploadSource**](docs/SourceContentApi.md#uploadsource) | **POST** /api/v1/resources/{resource_id}/content | Upload Source
*SubjectsAndReflectionApi* | [**addMembership**](docs/SubjectsAndReflectionApi.md#addmembership) | **PUT** /api/v1/subjects/{subject_id}/concepts/{concept_id} | Add Membership
*SubjectsAndReflectionApi* | [**createSubject**](docs/SubjectsAndReflectionApi.md#createsubject) | **POST** /api/v1/subjects | Create Subject
*SubjectsAndReflectionApi* | [**listSubjects**](docs/SubjectsAndReflectionApi.md#listsubjects) | **GET** /api/v1/subjects | List Subjects
*SubjectsAndReflectionApi* | [**reflect**](docs/SubjectsAndReflectionApi.md#reflect) | **GET** /api/v1/reflection | Reflect
*SubjectsAndReflectionApi* | [**reviewHistory**](docs/SubjectsAndReflectionApi.md#reviewhistory) | **GET** /api/v1/review-sessions | Review History
*SubjectsAndReflectionApi* | [**sessionDetail**](docs/SubjectsAndReflectionApi.md#sessiondetail) | **GET** /api/v1/review-sessions/{session_id} | Session Detail
*SubjectsAndReflectionApi* | [**subjectScope**](docs/SubjectsAndReflectionApi.md#subjectscope) | **GET** /api/v1/subjects/{subject_id}/scope | Subject Scope


### Models

- [ActiveQuestion](docs/ActiveQuestion.md)
- [Activity](docs/Activity.md)
- [ActivityPage](docs/ActivityPage.md)
- [ArchivePatch](docs/ArchivePatch.md)
- [ArchivedRelationshipRead](docs/ArchivedRelationshipRead.md)
- [ArtifactRead](docs/ArtifactRead.md)
- [AttemptCreate](docs/AttemptCreate.md)
- [AttemptRead](docs/AttemptRead.md)
- [BankCapture](docs/BankCapture.md)
- [BankDocument](docs/BankDocument.md)
- [BankResult](docs/BankResult.md)
- [CapabilityCheck](docs/CapabilityCheck.md)
- [CapabilitySettings](docs/CapabilitySettings.md)
- [CaptureCreate](docs/CaptureCreate.md)
- [CaptureDetail](docs/CaptureDetail.md)
- [CapturePage](docs/CapturePage.md)
- [CaptureRead](docs/CaptureRead.md)
- [CaptureReceipt](docs/CaptureReceipt.md)
- [ChatEndpoint](docs/ChatEndpoint.md)
- [ChunkPage](docs/ChunkPage.md)
- [ChunkRead](docs/ChunkRead.md)
- [Citation](docs/Citation.md)
- [ConceptDetail](docs/ConceptDetail.md)
- [ConceptMapRead](docs/ConceptMapRead.md)
- [ConceptPage](docs/ConceptPage.md)
- [ConceptPatch](docs/ConceptPatch.md)
- [ConceptSummary](docs/ConceptSummary.md)
- [ConfirmedMapEdge](docs/ConfirmedMapEdge.md)
- [ConversationPage](docs/ConversationPage.md)
- [ConversationRead](docs/ConversationRead.md)
- [ConversationSummary](docs/ConversationSummary.md)
- [Decision](docs/Decision.md)
- [DecisionRead](docs/DecisionRead.md)
- [Detail](docs/Detail.md)
- [EmbeddingEndpoint](docs/EmbeddingEndpoint.md)
- [ErrorResponse](docs/ErrorResponse.md)
- [HealthResponse](docs/HealthResponse.md)
- [ImportRead](docs/ImportRead.md)
- [ImportRequest](docs/ImportRequest.md)
- [LearningOutput](docs/LearningOutput.md)
- [LocInner](docs/LocInner.md)
- [MapLayout](docs/MapLayout.md)
- [MapNode](docs/MapNode.md)
- [MapPosition](docs/MapPosition.md)
- [MapRequest](docs/MapRequest.md)
- [MembershipRead](docs/MembershipRead.md)
- [MigrationRead](docs/MigrationRead.md)
- [MigrationRequest](docs/MigrationRequest.md)
- [ProbeRead](docs/ProbeRead.md)
- [Profile](docs/Profile.md)
- [ProgressRead](docs/ProgressRead.md)
- [ProposalPage](docs/ProposalPage.md)
- [ProposalRead](docs/ProposalRead.md)
- [ProposedMapEdge](docs/ProposedMapEdge.md)
- [QuestionRead](docs/QuestionRead.md)
- [QuickCapture](docs/QuickCapture.md)
- [ReadinessRead](docs/ReadinessRead.md)
- [ReflectionRead](docs/ReflectionRead.md)
- [ReflectionRevision](docs/ReflectionRevision.md)
- [RelatedResult](docs/RelatedResult.md)
- [RelationshipCreate](docs/RelationshipCreate.md)
- [RelationshipPage](docs/RelationshipPage.md)
- [RelationshipRead](docs/RelationshipRead.md)
- [ResourceCreate](docs/ResourceCreate.md)
- [ResourceDetail](docs/ResourceDetail.md)
- [ResourceLink](docs/ResourceLink.md)
- [ResourcePage](docs/ResourcePage.md)
- [ResourcePatch](docs/ResourcePatch.md)
- [ResourceRead](docs/ResourceRead.md)
- [ReviewHistory](docs/ReviewHistory.md)
- [ReviewHistoryItem](docs/ReviewHistoryItem.md)
- [ReviewSelection](docs/ReviewSelection.md)
- [ReviewSnapshot](docs/ReviewSnapshot.md)
- [RevisionCreate](docs/RevisionCreate.md)
- [RevisionPage](docs/RevisionPage.md)
- [RevisionRead](docs/RevisionRead.md)
- [SearchHit](docs/SearchHit.md)
- [SearchResult](docs/SearchResult.md)
- [SessionCreate](docs/SessionCreate.md)
- [SessionDetail](docs/SessionDetail.md)
- [SessionQuestionRead](docs/SessionQuestionRead.md)
- [SessionRead](docs/SessionRead.md)
- [SettingsRead](docs/SettingsRead.md)
- [SetupConfiguration](docs/SetupConfiguration.md)
- [SimilarityCandidate](docs/SimilarityCandidate.md)
- [SourceReceipt](docs/SourceReceipt.md)
- [SourceUpload](docs/SourceUpload.md)
- [SubjectCreate](docs/SubjectCreate.md)
- [SubjectList](docs/SubjectList.md)
- [SubjectRead](docs/SubjectRead.md)
- [SubjectScopeRead](docs/SubjectScopeRead.md)
- [Suggestion](docs/Suggestion.md)
- [SuggestionRead](docs/SuggestionRead.md)
- [TaskCreate](docs/TaskCreate.md)
- [TaskReceipt](docs/TaskReceipt.md)
- [TurnCreate](docs/TurnCreate.md)
- [TurnPage](docs/TurnPage.md)
- [TurnRead](docs/TurnRead.md)
- [ValidationErrorResponse](docs/ValidationErrorResponse.md)
- [ValidationIssue](docs/ValidationIssue.md)
- [WorkRead](docs/WorkRead.md)
- [WorkerRead](docs/WorkerRead.md)

### Authorization

Endpoints do not require authorization.


## About

This TypeScript SDK client supports the [Fetch API](https://fetch.spec.whatwg.org/)
and is automatically generated by the
[OpenAPI Generator](https://openapi-generator.tech) project:

- API version: `0.1.0`
- Package version: `0.1.0`
- Generator version: `7.26.0`
- Build package: `org.openapitools.codegen.languages.TypeScriptFetchClientCodegen`

The generated npm module supports the following:

- Environments
  * Node.js
  * Webpack
  * Browserify
- Language levels
  * ES5 - you must have a Promises/A+ library installed
  * ES6
- Module systems
  * CommonJS
  * ES6 module system


## Development

### Building

To build the TypeScript source code, you need to have Node.js and npm installed.
After cloning the repository, navigate to the project directory and run:

```bash
npm install
npm run build
```

### Publishing

Once you've built the package, you can publish it to npm:

```bash
npm publish
```

## License

[]()
